import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { projectLogic } from 'scenes/projectLogic'

import type { sandboxStreamLogicType } from './sandboxStreamLogicType'
import type {
    PermissionRequestRecord,
    StoredLogEntry,
    ThreadItem,
    ToolInvocation,
    ToolInvocationStatus,
} from './types/sandboxStreamTypes'

export type SandboxSseStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed' | 'error'
export type SandboxRunStatus = 'queued' | 'in_progress' | 'completed' | 'failed' | 'cancelled'

export interface SandboxStreamLogicProps {
    conversationId: string
}

/** Matches `mcp__posthog__exec` (and plugin/regional variants). Ported from Twig posthog-exec-display.ts. */
const POSTHOG_EXEC_TOOL_RE = /^mcp__(?:plugin_)?posthog(?:_[^_]+)*__exec$/

interface ResolvedToolKey {
    resolvedKey: string
    innerToolName?: string
    innerInput?: Record<string, unknown>
}

/**
 * Resolves the registry key for a tool call. The single-exec `posthog` MCP server exposes one
 * outer `exec` tool; the inner tool name is parsed out of `rawInput.command`. Non-exec MCP tools
 * and Claude built-ins look up by their wire name directly.
 */
export function resolveToolKey(serverName: string, toolName: string, input: Record<string, unknown>): ResolvedToolKey {
    const fullName = `mcp__${serverName}__${toolName}`

    if (POSTHOG_EXEC_TOOL_RE.test(fullName) && typeof input.command === 'string') {
        const verbMatch = input.command.match(/^\s*(tools|search|info|schema|call)(?:\s+([\s\S]*))?\s*$/)
        if (!verbMatch) {
            return { resolvedKey: '__posthog_exec_unknown__' }
        }

        const verb = verbMatch[1] as 'tools' | 'search' | 'info' | 'schema' | 'call'
        const rest = (verbMatch[2] ?? '').trim()

        if (verb !== 'call') {
            return { resolvedKey: `__posthog_exec_${verb}__` }
        }

        const callMatch = rest.match(/^(?:--json\s+)?([a-zA-Z0-9_-]+)\s*([\s\S]*)$/)
        if (!callMatch) {
            return { resolvedKey: '__posthog_exec_unknown__' }
        }

        const innerToolName = callMatch[1]
        const jsonBody = (callMatch[2] ?? '').trim()
        let innerInput: Record<string, unknown> = {}
        if (jsonBody) {
            try {
                innerInput = JSON.parse(jsonBody)
            } catch {
                // leave empty
            }
        }
        return { resolvedKey: innerToolName, innerToolName, innerInput }
    }

    return { resolvedKey: toolName }
}

/**
 * Finds the last assistant-message buffer for a wire message id, also matching the derived
 * `${id}@<n>` ids minted when the wire omits `messageId` and every message shares the fallback id.
 */
function findLastAssistantMessageIndex(state: ThreadItem[], id: string, incompleteOnly: boolean): number {
    for (let i = state.length - 1; i >= 0; i--) {
        const item = state[i]
        if (
            item.type === 'assistant_message' &&
            (item.id === id || item.id.startsWith(`${id}@`)) &&
            (!incompleteOnly || !item.complete)
        ) {
            return i
        }
    }
    return -1
}

function mapAcpStatus(status: unknown): ToolInvocationStatus {
    switch (status) {
        case 'in_progress':
            return 'in_progress'
        case 'completed':
            return 'completed'
        case 'failed':
            return 'failed'
        default:
            return 'pending'
    }
}

/**
 * Owns the `EventSource` to the products/tasks stream endpoint, parses the ACP wire format, and
 * produces thread-shaped state the renderer consumes. Coexistence sibling to `maxThreadLogic`'s
 * SSE loop — the sandbox path never enters the LangGraph EventSource loop.
 *
 * Covers open/close, `data.type === 'notification'` → `ingestAcpFrame` dispatch, terminal status,
 * and stream-error capture. Reconnect/backoff and content dedup are intentionally not implemented
 * here yet.
 *
 * Keyed by conversation id so concurrent conversations keep independent stream state and
 * EventSource connections.
 */
export const sandboxStreamLogic = kea<sandboxStreamLogicType>([
    props({} as SandboxStreamLogicProps),
    key((props) => props.conversationId),
    path((key) => ['scenes', 'max', 'sandboxStreamLogic', key]),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        openSseForRun: (payload: { taskId: string; runId: string; startLatest?: boolean }) => payload,
        closeSse: true,
        sseConnecting: true,
        sseOpened: true,
        /** Frame ingestion — called by the SSE listener and by products/tasks `logs/` replay. */
        ingestAcpFrame: (entry: StoredLogEntry) => ({ entry }),
        ingestPermissionRequest: (record: PermissionRequestRecord) => ({ record }),
        handleTerminalStatus: (status: { status: SandboxRunStatus; errorMessage?: string | null }) => status,
        handleStreamError: (envelope: { errorTitle: string; errorMessage?: string; retryable: boolean }) => envelope,
        // Internal state-folding actions emitted by ingestAcpFrame.
        appendAssistantChunk: (id: string, delta: string) => ({ id, delta }),
        finalizeAssistantMessage: (id: string, text: string) => ({ id, text }),
        upsertToolInvocation: (invocation: ToolInvocation) => ({ invocation }),
        updateToolInvocation: (toolCallId: string, patch: Partial<ToolInvocation>) => ({ toolCallId, patch }),
        setCurrentMode: (mode: string) => ({ mode }),
        setCurrentProgress: (progress: string) => ({ progress }),
        markRunStarted: true,
        markTurnComplete: true,
        /** Echoes the user's own message into the thread — the sandbox wire never replays it. */
        pushHumanMessage: (content: string) => ({ content }),
        pushErrorItem: (errorMessage: string) => ({ errorMessage }),
        reset: true,
    }),
    reducers({
        sseStatus: [
            'idle' as SandboxSseStatus,
            {
                sseConnecting: () => 'connecting',
                sseOpened: () => 'open',
                closeSse: () => 'closed',
                handleStreamError: () => 'error',
                reset: () => 'idle',
            },
        ],
        currentRunStatus: [
            null as SandboxRunStatus | null,
            {
                openSseForRun: () => 'queued',
                handleTerminalStatus: (_, { status }) => status,
                reset: () => null,
            },
        ],
        toolInvocations: [
            new Map<string, ToolInvocation>(),
            {
                upsertToolInvocation: (state, { invocation }) => {
                    const next = new Map(state)
                    next.set(invocation.toolCallId, invocation)
                    return next
                },
                updateToolInvocation: (state, { toolCallId, patch }) => {
                    const existing = state.get(toolCallId)
                    if (!existing) {
                        return state
                    }
                    const next = new Map(state)
                    next.set(toolCallId, { ...existing, ...patch })
                    return next
                },
                reset: () => new Map(),
            },
        ],
        threadItems: [
            [] as ThreadItem[],
            {
                appendAssistantChunk: (state, { id, delta }) => {
                    const idx = findLastAssistantMessageIndex(state, id, false)
                    if (idx === -1) {
                        return [...state, { id, type: 'assistant_message', text: delta, complete: false }]
                    }
                    if (state[idx].complete) {
                        // Never reopen a finalized buffer — a post-finalize chunk is a new message
                        // (the wire may omit messageId), so start a fresh bubble with a unique id.
                        return [
                            ...state,
                            { id: `${id}@${state.length}`, type: 'assistant_message', text: delta, complete: false },
                        ]
                    }
                    const next = [...state]
                    next[idx] = { ...next[idx], text: (next[idx].text ?? '') + delta }
                    return next
                },
                finalizeAssistantMessage: (state, { id, text }) => {
                    const idx = findLastAssistantMessageIndex(state, id, true)
                    if (idx === -1) {
                        return [...state, { id, type: 'assistant_message', text, complete: true }]
                    }
                    const next = [...state]
                    next[idx] = { ...next[idx], text, complete: true }
                    return next
                },
                upsertToolInvocation: (state, { invocation }) => {
                    if (
                        state.some(
                            (item) => item.type === 'tool_invocation' && item.toolCallId === invocation.toolCallId
                        )
                    ) {
                        return state
                    }
                    return [
                        ...state,
                        { id: invocation.toolCallId, type: 'tool_invocation', toolCallId: invocation.toolCallId },
                    ]
                },
                pushHumanMessage: (state, { content }) => [
                    ...state,
                    { id: `human-${state.length}`, type: 'human_message', text: content, complete: true },
                ],
                markTurnComplete: (state) => [...state, { id: `turn-${state.length}`, type: 'turn_separator' }],
                pushErrorItem: (state, { errorMessage }) => [
                    ...state,
                    { id: `error-${state.length}`, type: 'error', errorMessage },
                ],
                reset: () => [],
            },
        ],
        pendingPermissionRequest: [
            null as PermissionRequestRecord | null,
            {
                ingestPermissionRequest: (_, { record }) => record,
                reset: () => null,
            },
        ],
        currentMode: [
            null as string | null,
            {
                setCurrentMode: (_, { mode }) => mode,
                reset: () => null,
            },
        ],
        currentProgress: [
            null as string | null,
            {
                setCurrentProgress: (_, { progress }) => progress,
                markTurnComplete: () => null,
                reset: () => null,
            },
        ],
        runStarted: [
            false,
            {
                markRunStarted: () => true,
                reset: () => false,
            },
        ],
        turnComplete: [
            false,
            {
                markTurnComplete: () => true,
                markRunStarted: () => false,
                reset: () => false,
            },
        ],
    }),
    listeners(({ values, actions, cache }) => ({
        openSseForRun: ({ taskId, runId, startLatest }) => {
            const projectId = values.currentProjectId
            if (projectId === null) {
                actions.handleStreamError({ errorTitle: 'No current project', retryable: false })
                return
            }

            actions.sseConnecting()

            // Replace any prior connection — reconnect/backoff layers on top of this later.
            cache.disposables.dispose('event-source')
            // pauseOnPageHidden: false — a live SSE connection must survive tab hides; re-running
            // setup on show would replay the stream from the top and duplicate thread state.
            cache.disposables.add(
                (): (() => void) => {
                    const start = startLatest ? '?start=latest' : ''
                    const url = `/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/stream/${start}`
                    const eventSource = new EventSource(url, { withCredentials: true })

                    eventSource.onopen = (): void => actions.sseOpened()
                    eventSource.onmessage = (event: MessageEvent<string>): void => {
                        let data: { type?: string } & Record<string, unknown>
                        try {
                            data = JSON.parse(event.data)
                        } catch {
                            return
                        }
                        switch (data.type) {
                            case 'notification':
                                actions.ingestAcpFrame(data as unknown as StoredLogEntry)
                                break
                            case 'task_run_state':
                                actions.handleTerminalStatus({
                                    status: data.status as SandboxRunStatus,
                                    errorMessage: (data.errorMessage as string | null) ?? null,
                                })
                                break
                            case 'keepalive':
                                break
                            default:
                                break
                        }
                    }
                    // Named `event: error` frames sent by the stream endpoint.
                    eventSource.addEventListener('error', (event: MessageEvent<string>): void => {
                        if (typeof event.data === 'string' && event.data.length > 0) {
                            try {
                                const envelope = JSON.parse(event.data)
                                actions.handleStreamError({
                                    errorTitle: envelope.errorTitle ?? 'Cloud stream failed',
                                    errorMessage: envelope.errorMessage,
                                    retryable: envelope.retryable ?? true,
                                })
                            } catch {
                                actions.handleStreamError({ errorTitle: 'Cloud stream failed', retryable: true })
                            }
                        }
                    })

                    return () => eventSource.close()
                },
                'event-source',
                { pauseOnPageHidden: false }
            )
        },
        closeSse: () => {
            cache.disposables.dispose('event-source')
        },
        reset: () => {
            cache.disposables.dispose('event-source')
        },
        ingestAcpFrame: ({ entry }) => {
            const notification = entry?.notification
            if (!notification) {
                return
            }
            const method = notification.method
            const params = (notification.params ?? {}) as Record<string, any>

            // Custom `_posthog/*` notification namespace emitted by the agent-server.
            if (method === '_posthog/run_started') {
                actions.markRunStarted()
                return
            }
            if (method === '_posthog/turn_complete') {
                actions.markTurnComplete()
                return
            }
            if (method === '_posthog/progress') {
                actions.setCurrentProgress(String(params.message ?? params.progress ?? ''))
                return
            }
            if (method === '_posthog/error') {
                actions.pushErrorItem(String(params.message ?? notification.error?.message ?? 'Agent error'))
                return
            }
            if (method?.startsWith('_posthog/')) {
                // _posthog/usage_update, _posthog/console, _posthog/sdk_session, _posthog/git_checkpoint, ...
                return
            }

            if (method !== 'session/update') {
                return
            }

            const update = (params.update ?? {}) as Record<string, any>
            const sessionUpdate = update.sessionUpdate as string | undefined

            switch (sessionUpdate) {
                case 'agent_message_chunk': {
                    const id = String(update.messageId ?? 'current')
                    actions.appendAssistantChunk(id, String(update.content?.text ?? update.text ?? ''))
                    break
                }
                case 'agent_message': {
                    const id = String(update.messageId ?? 'current')
                    actions.finalizeAssistantMessage(id, String(update.content?.text ?? update.text ?? ''))
                    break
                }
                case 'tool_call': {
                    const toolCallId = String(update.toolCallId ?? '')
                    if (!toolCallId) {
                        break
                    }
                    const rawServerName = String(update.serverName ?? 'posthog')
                    const rawToolName = String(update.toolName ?? update.title ?? '')
                    const input = (update.rawInput ?? update.input ?? {}) as Record<string, unknown>
                    const { resolvedKey, innerToolName, innerInput } = resolveToolKey(rawServerName, rawToolName, input)
                    actions.upsertToolInvocation({
                        toolCallId,
                        rawServerName,
                        rawToolName,
                        innerToolName,
                        resolvedKey,
                        input,
                        innerInput,
                        status: mapAcpStatus(update.status),
                        title: update.title as string | undefined,
                        kind: update.kind as string | undefined,
                        locations: update.locations as { path: string; line?: number }[] | undefined,
                        contentBlocks: Array.isArray(update.content) ? update.content : [],
                    })
                    break
                }
                case 'tool_call_update': {
                    const toolCallId = String(update.toolCallId ?? '')
                    if (!toolCallId) {
                        break
                    }
                    const existing = values.toolInvocations.get(toolCallId)
                    const mergedContent = existing
                        ? [...existing.contentBlocks, ...(Array.isArray(update.content) ? update.content : [])]
                        : Array.isArray(update.content)
                          ? update.content
                          : []
                    const status = mapAcpStatus(update.status ?? existing?.status)
                    const errorMessage =
                        (update.error?.message as string | undefined) ??
                        (status === 'failed' ? notification.error?.message : undefined)
                    actions.updateToolInvocation(toolCallId, {
                        status,
                        title: (update.title as string | undefined) ?? existing?.title,
                        progress: update.progress ?? existing?.progress,
                        output: update.rawOutput ?? existing?.output,
                        locations:
                            (update.locations as { path: string; line?: number }[] | undefined) ?? existing?.locations,
                        contentBlocks: mergedContent,
                        error: errorMessage !== undefined ? { message: errorMessage } : existing?.error,
                    })
                    break
                }
                case 'current_mode_update': {
                    actions.setCurrentMode(String(update.currentModeId ?? update.mode ?? ''))
                    break
                }
                default:
                    break
            }
        },
    })),
])
