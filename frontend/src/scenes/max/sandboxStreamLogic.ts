import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { apiHostOrigin } from 'lib/utils/apiHost'

import { resolveToolKey } from './mcpToolRegistry'
import type { sandboxStreamLogicType } from './sandboxStreamLogicType'
import {
    AcpSessionUpdate,
    PermissionRequestRecord,
    RunStatus,
    SseStatus,
    StoredLogEntry,
    ThreadItem,
    ToolInvocation,
    ToolInvocationLocation,
    ToolInvocationStatus,
} from './types/sandboxStreamTypes'

/**
 * Owns the direct browser->cloud-agent SSE connection for the sandbox runtime and folds
 * the ACP wire format into thread-shaped state. Modeled on the proven in-repo consumer
 * products/tasks/frontend/logics/taskDetailSceneLogic.ts startStreaming: a fetch-reader
 * with Last-Event-ID resume, per-event dedup, keepalive skipping, and an AbortController
 * registered via cache.disposables.
 *
 * I1.3 scope: skeleton + SSE ownership + a pure `ingestAcpFrame` fold. Reconnect/backoff
 * hardening (capped exponential, terminal-status refetch, error-class mapping) is DEFERRED
 * to I2.6 — kept minimal but correct here. See docs/internal/posthog-ai-migration/02_CORE.md §6.
 */

export interface SandboxStreamLogicProps {
    /** Threads its key so per-conversation stream state stays isolated. */
    conversationKey: string
}

export interface SandboxStreamState {
    toolInvocations: Record<string, ToolInvocation>
    threadItems: ThreadItem[]
    runStarted: boolean
    turnComplete: boolean
    currentMode?: string
    currentProgress?: string
    /** Serialized-JSON hashes of ingested frames, for /log/-replay vs live-SSE dedup. */
    ingestedEntryHashes: string[]
}

export const EMPTY_STREAM_STATE: SandboxStreamState = {
    toolInvocations: {},
    threadItems: [],
    runStarted: false,
    turnComplete: false,
    ingestedEntryHashes: [],
}

interface ParsedSseEvent {
    data: string
    eventType: string | null
    id: string | null
}

/** Parse one SSE block into its `data` / `event:` / `id:` fields. Ported from taskDetailSceneLogic. */
function parseSseEventBlock(block: string): ParsedSseEvent | null {
    let data = ''
    let eventType: string | null = null
    let id: string | null = null

    for (const line of block.split('\n')) {
        if (!line || line.startsWith(':')) {
            continue
        }
        if (line.startsWith('event:')) {
            eventType = line.slice(6).trim() || null
            continue
        }
        if (line.startsWith('id:')) {
            id = line.slice(3).trim() || null
            continue
        }
        if (line.startsWith('data:')) {
            data = data ? `${data}\n${line.slice(5).trimStart()}` : line.slice(5).trimStart()
        }
    }

    if (!data && !eventType && !id) {
        return null
    }
    return { data, eventType, id }
}

function normalizeStatus(status?: string): ToolInvocationStatus {
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

function getNotification(entry: StoredLogEntry): { method?: string; params?: Record<string, unknown> } | null {
    if (entry.type !== 'notification' || !entry.notification) {
        return null
    }
    return { method: entry.notification.method, params: entry.notification.params }
}

function appendAssistantText(state: SandboxStreamState, id: string, text: string, complete: boolean): ThreadItem[] {
    const items = [...state.threadItems]
    const last = items[items.length - 1]
    if (last && last.kind === 'assistant_message' && !last.complete) {
        items[items.length - 1] = { ...last, text: last.text + text, complete }
        return items
    }
    items.push({ kind: 'assistant_message', id, text, complete })
    return items
}

/**
 * Pure fold of one ACP frame into stream state. Dispatches on `notification.method`
 * (`session/update` discriminated further by `params.update.sessionUpdate`, plus the
 * `_posthog/*` lifecycle methods). Easily unit-testable from StoredLogEntry fixtures.
 * See the dispatch table in docs/internal/posthog-ai-migration/02_CORE.md §6.3.
 */
export function ingestAcpFrame(state: SandboxStreamState, entry: StoredLogEntry, frameId: string): SandboxStreamState {
    const notification = getNotification(entry)
    if (!notification?.method) {
        return state
    }
    const { method, params } = notification

    if (method === 'session/update') {
        const update = (params as { update?: AcpSessionUpdate } | undefined)?.update
        if (!update?.sessionUpdate) {
            return state
        }
        return ingestSessionUpdate(state, update, frameId)
    }

    switch (method) {
        case '_posthog/run_started':
            return { ...state, runStarted: true }
        case '_posthog/turn_complete':
            return {
                ...state,
                turnComplete: true,
                threadItems: [...state.threadItems, { kind: 'turn_complete', id: frameId }],
            }
        case '_posthog/progress':
            return { ...state, currentProgress: (params as { message?: string } | undefined)?.message }
        case '_posthog/error': {
            const message = (params as { message?: string } | undefined)?.message ?? 'Unknown error'
            return {
                ...state,
                threadItems: [...state.threadItems, { kind: 'error', id: frameId, message }],
            }
        }
        default:
            // _posthog/usage_update, _posthog/console, _posthog/sdk_session, etc. — ignore.
            return state
    }
}

function ingestSessionUpdate(state: SandboxStreamState, update: AcpSessionUpdate, frameId: string): SandboxStreamState {
    switch (update.sessionUpdate) {
        case 'agent_message_chunk':
            if (update.content?.type === 'text' && update.content.text) {
                return { ...state, threadItems: appendAssistantText(state, frameId, update.content.text, false) }
            }
            return state

        case 'agent_message':
            if (update.content?.type === 'text' && update.content.text) {
                return { ...state, threadItems: appendAssistantText(state, frameId, update.content.text, true) }
            }
            return state

        case 'current_mode_update':
            return { ...state, currentMode: (update as { currentModeId?: string }).currentModeId ?? state.currentMode }

        case 'tool_call':
            return ingestToolCall(state, update, frameId)

        case 'tool_call_update':
            return ingestToolCallUpdate(state, update)

        default:
            return state
    }
}

function ingestToolCall(state: SandboxStreamState, update: AcpSessionUpdate, frameId: string): SandboxStreamState {
    const toolCallId = update.toolCallId || frameId
    const rawServerName = update._meta?.serverName ?? ''
    const rawToolName = update._meta?.claudeCode?.toolName ?? update.title ?? 'unknown'
    const input = update.rawInput ?? {}
    const { resolvedKey, innerToolName, innerInput } = resolveToolKey(rawServerName, rawToolName, input)

    const invocation: ToolInvocation = {
        toolCallId,
        rawServerName,
        rawToolName,
        innerToolName,
        resolvedKey,
        input,
        innerInput,
        status: normalizeStatus(update.status),
        title: update.title,
        kind: update.kind,
        locations: update.locations as ToolInvocationLocation[] | undefined,
        contentBlocks: update.content ? [update.content] : [],
    }

    const alreadyHasItem = state.threadItems.some(
        (item) => item.kind === 'tool_invocation' && item.toolCallId === toolCallId
    )
    return {
        ...state,
        toolInvocations: { ...state.toolInvocations, [toolCallId]: invocation },
        threadItems: alreadyHasItem
            ? state.threadItems
            : [...state.threadItems, { kind: 'tool_invocation', toolCallId }],
    }
}

function ingestToolCallUpdate(state: SandboxStreamState, update: AcpSessionUpdate): SandboxStreamState {
    const toolCallId = update.toolCallId
    if (!toolCallId) {
        return state
    }
    const existing = state.toolInvocations[toolCallId]
    if (!existing) {
        return state
    }

    const merged: ToolInvocation = {
        ...existing,
        status: normalizeStatus(update.status),
        title: update.title ?? existing.title,
        kind: update.kind ?? existing.kind,
        locations: (update.locations as ToolInvocationLocation[] | undefined) ?? existing.locations,
        contentBlocks: update.content ? [...existing.contentBlocks, update.content] : existing.contentBlocks,
        progress: update.rawOutput ?? existing.progress,
        output:
            update._meta?.claudeCode?.toolResponse !== undefined
                ? update._meta.claudeCode.toolResponse
                : update.rawOutput !== undefined
                  ? update.rawOutput
                  : existing.output,
    }
    return { ...state, toolInvocations: { ...state.toolInvocations, [toolCallId]: merged } }
}

export const sandboxStreamLogic = kea<sandboxStreamLogicType>([
    path((key) => ['scenes', 'max', 'sandboxStreamLogic', key]),
    props({} as SandboxStreamLogicProps),
    key((props) => props.conversationKey),

    actions({
        /** Open the SSE connection for a cloud-agent run. */
        openSseForRun: (payload: { taskId: string; runId: string; startLatest?: boolean }) => payload,
        /** Close the SSE connection (conversation change / unmount). */
        closeSse: true,
        setSseStatus: (status: SseStatus) => ({ status }),
        setLastEventId: (lastEventId: string) => ({ lastEventId }),
        setCurrentRunStatus: (status: RunStatus) => ({ status }),
        markEventSeen: (eventId: string) => ({ eventId }),
        /** Fold one ACP frame into stream state (called by the SSE listener and /log/ replay). */
        ingestFrame: (entry: StoredLogEntry, frameId: string) => ({ entry, frameId }),
        ingestPermissionRequest: (record: PermissionRequestRecord) => ({ record }),
        /** Reset all stream state — called when the conversation changes. */
        reset: true,
    }),

    reducers({
        stream: [
            EMPTY_STREAM_STATE,
            {
                ingestFrame: (state, { entry, frameId }) => ingestAcpFrame(state, entry, frameId),
                reset: () => EMPTY_STREAM_STATE,
            },
        ],
        sseStatus: [
            'idle' as SseStatus,
            {
                openSseForRun: () => 'connecting',
                setSseStatus: (_, { status }) => status,
                closeSse: () => 'closed',
                reset: () => 'idle',
            },
        ],
        lastEventId: [
            undefined as string | undefined,
            {
                setLastEventId: (_, { lastEventId }) => lastEventId,
                reset: () => undefined,
            },
        ],
        seenEventIds: [
            {} as Record<string, true>,
            {
                markEventSeen: (state, { eventId }) => ({ ...state, [eventId]: true }),
                reset: () => ({}),
            },
        ],
        currentRunStatus: [
            undefined as RunStatus | undefined,
            {
                setCurrentRunStatus: (_, { status }) => status,
                reset: () => undefined,
            },
        ],
        pendingPermissionRequest: [
            undefined as PermissionRequestRecord | undefined,
            {
                ingestPermissionRequest: (_, { record }) => record,
                reset: () => undefined,
            },
        ],
    }),

    selectors({
        toolInvocations: [(s) => [s.stream], (stream): Record<string, ToolInvocation> => stream.toolInvocations],
        threadItems: [(s) => [s.stream], (stream): ThreadItem[] => stream.threadItems],
        runStarted: [(s) => [s.stream], (stream): boolean => stream.runStarted],
        turnComplete: [(s) => [s.stream], (stream): boolean => stream.turnComplete],
        currentProgress: [(s) => [s.stream], (stream): string | undefined => stream.currentProgress],
    }),

    listeners(({ actions, values, cache }) => ({
        openSseForRun: ({ taskId, runId }) => {
            // Tear down any previous stream first — same key replaces it.
            cache.disposables.dispose('sseStream')

            cache.disposables.add(() => {
                const abortController = new AbortController()
                // Direct browser->cloud-agent SSE (DECISION 3 "Option B"); session-cookie auth.
                const streamUrl = `${apiHostOrigin()}/api/projects/@current/tasks/${taskId}/runs/${runId}/stream/`

                const consume = async (): Promise<void> => {
                    try {
                        actions.setSseStatus('connecting')
                        const response = await fetch(streamUrl, {
                            signal: abortController.signal,
                            headers: {
                                Accept: 'text/event-stream',
                                ...(values.lastEventId ? { 'Last-Event-ID': values.lastEventId } : {}),
                            },
                        })

                        if (!response.ok || !response.body) {
                            actions.setSseStatus('error')
                            return
                        }
                        actions.setSseStatus('open')

                        const reader = response.body.getReader()
                        const decoder = new TextDecoder()
                        let buffer = ''
                        let frameIndex = values.stream.threadItems.length

                        while (true) {
                            const { done, value } = await reader.read()
                            if (done) {
                                break
                            }
                            buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
                            const blocks = buffer.split('\n\n')
                            buffer = blocks.pop() || ''

                            for (const block of blocks) {
                                const parsed = parseSseEventBlock(block)
                                if (!parsed || parsed.eventType === 'keepalive' || !parsed.data) {
                                    continue
                                }
                                if (parsed.id) {
                                    if (values.seenEventIds[parsed.id]) {
                                        continue
                                    }
                                    actions.markEventSeen(parsed.id)
                                    actions.setLastEventId(parsed.id)
                                }
                                try {
                                    const entry = JSON.parse(parsed.data) as StoredLogEntry
                                    actions.ingestFrame(
                                        entry,
                                        parsed.id ? `stream-${parsed.id}` : `stream-${frameIndex++}`
                                    )
                                } catch {
                                    // Skip invalid JSON frames.
                                }
                            }
                        }
                        actions.setSseStatus('closed')
                    } catch (e) {
                        if ((e as Error).name === 'AbortError') {
                            return
                        }
                        // Reconnect/backoff is deferred to I2.6 — surface the error state for now.
                        actions.setSseStatus('error')
                    }
                }

                void consume()
                return () => abortController.abort()
            }, 'sseStream')
        },
        closeSse: () => {
            cache.disposables.dispose('sseStream')
        },
        reset: () => {
            cache.disposables.dispose('sseStream')
        },
    })),
])
