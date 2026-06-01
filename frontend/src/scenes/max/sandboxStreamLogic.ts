import { actions, connect, kea, listeners, path, reducers } from 'kea'

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
 * and Claude built-ins look up by their wire name directly. See 03_RICH_UI.md § 2.2.
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
 * I1 skeleton: open/close, `data.type === 'notification'` → `ingestAcpFrame`, the § 6.3 dispatch
 * table, terminal status, and stream-error surfacing. Reconnect/backoff and content dedup land in
 * I2.6 (02_CORE.md §§ 4.3, 4.4, 6). See 02_CORE.md § 6.
 */
export const sandboxStreamLogic = kea<sandboxStreamLogicType>([
    path(['scenes', 'max', 'sandboxStreamLogic']),
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
                    const idx = state.findIndex((item) => item.type === 'assistant_message' && item.id === id)
                    if (idx === -1) {
                        return [...state, { id, type: 'assistant_message', text: delta, complete: false }]
                    }
                    const next = [...state]
                    next[idx] = { ...next[idx], text: (next[idx].text ?? '') + delta }
                    return next
                },
                finalizeAssistantMessage: (state, { id, text }) => {
                    const idx = state.findIndex((item) => item.type === 'assistant_message' && item.id === id)
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

            // Replace any prior connection — I2.6 layers reconnect/backoff on top of this.
            cache.disposables.dispose('event-source')
            cache.disposables.add((): (() => void) => {
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
                // Named `event: error` frames (02_CORE.md § 4.1).
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
            }, 'event-source')
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

            // Custom `_posthog/*` namespace — § 6.3.
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
                    actions.updateToolInvocation(toolCallId, {
                        status: mapAcpStatus(update.status ?? existing?.status),
                        title: (update.title as string | undefined) ?? existing?.title,
                        progress: update.progress ?? existing?.progress,
                        output: update.rawOutput ?? existing?.output,
                        locations:
                            (update.locations as { path: string; line?: number }[] | undefined) ?? existing?.locations,
                        contentBlocks: mergedContent,
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
