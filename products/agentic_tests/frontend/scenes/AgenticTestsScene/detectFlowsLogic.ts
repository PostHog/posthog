import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { LogEntry, parseLogEvent } from 'products/tasks/frontend/lib/parse-logs'
import { TaskRun, TaskRunStatus } from 'products/tasks/frontend/types'

import { agenticTestsSceneLogic } from './agenticTestsSceneLogic'
import type { detectFlowsLogicType } from './detectFlowsLogicType'

// Copied from taskDetailSceneLogic — not exported from tasks product
interface ParsedSseEvent {
    data: string
    eventType: string | null
    id: string | null
}

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

function buildToolMap(entries: LogEntry[]): Map<string, LogEntry> {
    const toolMap = new Map<string, LogEntry>()
    for (const entry of entries) {
        if (entry.type === 'tool' && entry.toolCallId) {
            toolMap.set(entry.toolCallId, { ...entry })
        }
    }
    return toolMap
}

function isTerminalStatus(status: string): boolean {
    return status === TaskRunStatus.COMPLETED || status === TaskRunStatus.FAILED || status === TaskRunStatus.CANCELLED
}

const LOG_POLL_INTERVAL_MS = 2000

export const detectFlowsLogic = kea<detectFlowsLogicType>([
    path(['products', 'agentic_tests', 'frontend', 'scenes', 'AgenticTestsScene', 'detectFlowsLogic']),

    connect({ actions: [agenticTestsSceneLogic, ['loadTests', 'loadTestsSuccess']] }),

    actions({
        openFormModal: true,
        closeFormModal: true,
        openLogsModal: true,
        closeLogsModal: true,
        setIntegrationId: (integrationId: number | null) => ({ integrationId }),
        setRepository: (repository: string) => ({ repository }),
        setDomain: (domain: string) => ({ domain }),
        submitDetectFlows: true,
        submitDetectFlowsSuccess: (taskId: string, taskRunId: string) => ({ taskId, taskRunId }),
        submitDetectFlowsFailure: true,
        restoreActiveRun: (taskId: string, taskRunId: string) => ({ taskId, taskRunId }),
        restoreTerminalRun: (taskId: string, taskRunId: string, runStatus: TaskRunStatus) => ({
            taskId,
            taskRunId,
            runStatus,
        }),
        startStreaming: true,
        stopStreaming: true,
        startPolling: true,
        stopPolling: true,
        appendStreamEntries: (entries: LogEntry[]) => ({ entries }),
        updateStreamEntries: (entries: LogEntry[]) => ({ entries }),
        recordStreamProgress: (lastEventId: string | null, seenEventIds: string[]) => ({
            lastEventId,
            seenEventIds,
        }),
        setRunStatus: (status: TaskRunStatus) => ({ status }),
        detectionComplete: (proposedCount: number) => ({ proposedCount }),
        dismissBanner: true,
    }),

    reducers({
        formModalOpen: [
            false,
            {
                openFormModal: () => true,
                closeFormModal: () => false,
                submitDetectFlowsSuccess: () => false,
            },
        ],
        logsModalOpen: [
            false,
            {
                openLogsModal: () => true,
                closeLogsModal: () => false,
            },
        ],
        integrationId: [null as number | null, { setIntegrationId: (_, { integrationId }) => integrationId }],
        repository: ['', { setRepository: (_, { repository }) => repository }],
        domain: ['', { setDomain: (_, { domain }) => domain }],
        submitting: [
            false,
            {
                submitDetectFlows: () => true,
                submitDetectFlowsSuccess: () => false,
                submitDetectFlowsFailure: () => false,
            },
        ],
        taskId: [
            null as string | null,
            {
                submitDetectFlowsSuccess: (_, { taskId }) => taskId,
                restoreActiveRun: (_, { taskId }) => taskId,
                restoreTerminalRun: (_, { taskId }) => taskId,
                dismissBanner: () => null,
            },
        ],
        taskRunId: [
            null as string | null,
            {
                submitDetectFlowsSuccess: (_, { taskRunId }) => taskRunId,
                restoreActiveRun: (_, { taskRunId }) => taskRunId,
                restoreTerminalRun: (_, { taskRunId }) => taskRunId,
                dismissBanner: () => null,
            },
        ],
        streamEntries: [
            [] as LogEntry[],
            {
                submitDetectFlowsSuccess: () => [],
                restoreActiveRun: () => [],
                appendStreamEntries: (state, { entries }) => {
                    if (entries.length === 0) {
                        return state
                    }
                    const last = state[state.length - 1]
                    const first = entries[0]
                    if (last?.type === first.type && (first.type === 'agent' || first.type === 'thinking')) {
                        return [
                            ...state.slice(0, -1),
                            { ...last, message: (last.message || '') + (first.message || '') },
                            ...entries.slice(1),
                        ]
                    }
                    return [...state, ...entries]
                },
                updateStreamEntries: (state, { entries }) => {
                    if (entries.length === 0) {
                        return state
                    }
                    const entriesById = new Map(entries.map((entry) => [entry.id, entry]))
                    let changed = false
                    const nextState = state.map((entry) => {
                        const updatedEntry = entriesById.get(entry.id)
                        if (!updatedEntry) {
                            return entry
                        }
                        changed = true
                        return updatedEntry
                    })
                    return changed ? nextState : state
                },
                dismissBanner: () => [],
            },
        ],
        lastStreamEventId: [
            null as string | null,
            {
                submitDetectFlowsSuccess: () => null,
                restoreActiveRun: () => null,
                recordStreamProgress: (state, { lastEventId }) => lastEventId ?? state,
                dismissBanner: () => null,
            },
        ],
        seenStreamEventIds: [
            {} as Record<string, true>,
            {
                submitDetectFlowsSuccess: () => ({}),
                restoreActiveRun: () => ({}),
                stopStreaming: () => ({}),
                recordStreamProgress: (state, { seenEventIds }) => {
                    if (seenEventIds.length === 0) {
                        return state
                    }
                    return {
                        ...state,
                        ...Object.fromEntries(seenEventIds.map((eventId) => [eventId, true as const])),
                    }
                },
                dismissBanner: () => ({}),
            },
        ],
        isStreaming: [
            false,
            {
                startStreaming: () => true,
                stopStreaming: () => false,
                dismissBanner: () => false,
            },
        ],
        runStatus: [
            null as TaskRunStatus | null,
            {
                submitDetectFlowsSuccess: () => TaskRunStatus.QUEUED,
                restoreActiveRun: () => TaskRunStatus.IN_PROGRESS,
                restoreTerminalRun: (_, { runStatus }) => runStatus,
                setRunStatus: (_, { status }) => status,
                dismissBanner: () => null,
            },
        ],
        proposedCount: [
            null as number | null,
            {
                detectionComplete: (_, { proposedCount }) => proposedCount,
                dismissBanner: () => null,
            },
        ],
        // Snapshot of proposed count before detection completes, used to compute delta
        _previousProposedCount: [
            0,
            {
                setRunStatus: (state, { status }) => {
                    // Capture count right as we detect terminal status
                    if (isTerminalStatus(status)) {
                        return agenticTestsSceneLogic.findMounted()?.values.proposedCount ?? state
                    }
                    return state
                },
            },
        ],
    }),

    selectors({
        bannerVisible: [(s) => [s.taskId], (taskId): boolean => taskId !== null],
        step: [
            (s) => [s.runStatus, s.isTerminal],
            (runStatus, isTerminal): 1 | 2 | 3 => {
                if (isTerminal) {
                    return 3
                }
                if (runStatus === TaskRunStatus.IN_PROGRESS) {
                    return 2
                }
                return 1
            },
        ],
        isTerminal: [(s) => [s.runStatus], (runStatus): boolean => (runStatus ? isTerminalStatus(runStatus) : false)],
        isFailed: [
            (s) => [s.runStatus],
            (runStatus): boolean => runStatus === TaskRunStatus.FAILED || runStatus === TaskRunStatus.CANCELLED,
        ],
        canSubmit: [
            (s) => [s.repository, s.domain, s.submitting],
            (repository, domain, submitting): boolean => !!repository && !!domain && !submitting,
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        submitDetectFlows: async () => {
            try {
                const baseUrl = `api/projects/${getCurrentTeamId()}/agentic_tests/`
                const response = await api.create<{ task_id: string; task_run_id: string }>(`${baseUrl}detect_flows/`, {
                    repository: values.repository,
                    domain: values.domain,
                })
                actions.submitDetectFlowsSuccess(response.task_id, response.task_run_id)
            } catch (e) {
                actions.submitDetectFlowsFailure()
                lemonToast.error('Failed to start flow detection. Check that the GitHub integration is set up.')
                throw e
            }
        },

        submitDetectFlowsSuccess: () => {
            actions.startStreaming()
        },

        restoreActiveRun: () => {
            actions.startStreaming()
        },

        // When terminal status is detected (from stream or polling), reload tests
        setRunStatus: ({ status }) => {
            if (isTerminalStatus(status)) {
                actions.stopPolling()
                actions.loadTests()
            }
        },

        // After tests reload, compute proposed count delta and show toast
        loadTestsSuccess: () => {
            if (!values.isTerminal || values.proposedCount !== null) {
                return
            }
            const newCount = agenticTestsSceneLogic.findMounted()?.values.proposedCount ?? 0
            const delta = Math.max(0, newCount - values._previousProposedCount)
            actions.detectionComplete(delta)
            if (!values.isFailed) {
                lemonToast.success(
                    delta > 0
                        ? `Flow detection complete. ${delta} test${delta !== 1 ? 's' : ''} proposed.`
                        : 'Flow detection complete.'
                )
            } else {
                lemonToast.error('Flow detection failed.')
            }
        },

        startStreaming: () => {
            actions.stopPolling()

            cache.disposables.add(() => {
                const abortController = new AbortController()
                const { taskId, taskRunId } = values
                if (!taskId || !taskRunId) {
                    return () => {}
                }

                const streamUrl = `/api/projects/@current/tasks/${taskId}/runs/${taskRunId}/stream/`
                const toolMap = buildToolMap(values.streamEntries)
                let eventIndex = values.streamEntries.length

                const consume = async (): Promise<void> => {
                    try {
                        const response = await fetch(streamUrl, {
                            signal: abortController.signal,
                            headers: {
                                Accept: 'text/event-stream',
                                ...(values.lastStreamEventId ? { 'Last-Event-ID': values.lastStreamEventId } : {}),
                            },
                        })

                        if (!response.ok || !response.body) {
                            actions.stopStreaming()
                            actions.startPolling()
                            return
                        }

                        const reader = response.body.getReader()
                        const decoder = new TextDecoder()
                        let buffer = ''

                        while (true) {
                            const { done, value } = await reader.read()
                            if (done) {
                                break
                            }

                            buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
                            const blocks = buffer.split('\n\n')
                            buffer = blocks.pop() || ''

                            const batch: LogEntry[] = []
                            const updatedEntriesById = new Map<string, LogEntry>()
                            let lastProcessedEventId: string | null = null
                            const newlySeenEventIds: string[] = []

                            for (const block of blocks) {
                                const parsedEvent = parseSseEventBlock(block)
                                if (!parsedEvent || parsedEvent.eventType === 'keepalive' || !parsedEvent.data) {
                                    continue
                                }

                                if (parsedEvent.id) {
                                    if (
                                        values.seenStreamEventIds[parsedEvent.id] ||
                                        newlySeenEventIds.includes(parsedEvent.id)
                                    ) {
                                        continue
                                    }
                                    newlySeenEventIds.push(parsedEvent.id)
                                    lastProcessedEventId = parsedEvent.id
                                }

                                try {
                                    const event = JSON.parse(parsedEvent.data) as Record<string, unknown>

                                    if (event.type === 'task_run_state' && typeof event.status === 'string') {
                                        actions.setRunStatus(event.status as TaskRunStatus)
                                    }

                                    const entryId = parsedEvent.id
                                        ? `stream-${parsedEvent.id}`
                                        : `stream-${eventIndex++}`
                                    const entry = parseLogEvent(event, entryId, toolMap, (updatedEntry) => {
                                        updatedEntriesById.set(updatedEntry.id, updatedEntry)
                                    })
                                    if (entry) {
                                        const last = batch[batch.length - 1]
                                        if (
                                            last?.type === entry.type &&
                                            (entry.type === 'agent' || entry.type === 'thinking')
                                        ) {
                                            last.message = (last.message || '') + (entry.message || '')
                                        } else {
                                            batch.push(entry)
                                        }
                                    }
                                } catch {
                                    // Skip invalid JSON
                                }
                            }

                            if (newlySeenEventIds.length > 0) {
                                actions.recordStreamProgress(lastProcessedEventId, newlySeenEventIds)
                            }
                            if (updatedEntriesById.size > 0) {
                                actions.updateStreamEntries(Array.from(updatedEntriesById.values()))
                            }
                            if (batch.length > 0) {
                                actions.appendStreamEntries(batch)
                            }
                        }

                        // Stream ended — do a final status poll
                        actions.stopStreaming()
                        try {
                            const run = await api.get<TaskRun>(
                                `/api/projects/@current/tasks/${values.taskId}/runs/${values.taskRunId}/`
                            )
                            actions.setRunStatus(run.status as TaskRunStatus)
                            if (!isTerminalStatus(run.status)) {
                                actions.startPolling()
                            }
                        } catch {
                            actions.startPolling()
                        }
                    } catch (e) {
                        if ((e as Error).name === 'AbortError') {
                            return
                        }
                        actions.stopStreaming()
                        actions.startPolling()
                    }
                }

                consume()
                return () => abortController.abort()
            }, 'detectFlowsStream')
        },

        stopStreaming: () => {
            cache.disposables.dispose('detectFlowsStream')
        },

        startPolling: () => {
            cache.disposables.add(() => {
                const intervalId = window.setInterval(async () => {
                    const { taskId: tId, taskRunId: rId } = values
                    if (!tId || !rId) {
                        return
                    }
                    try {
                        const run = await api.get<TaskRun>(`/api/projects/@current/tasks/${tId}/runs/${rId}/`)
                        actions.setRunStatus(run.status as TaskRunStatus)
                    } catch {
                        // Retry on next poll
                    }
                }, LOG_POLL_INTERVAL_MS)
                return () => clearInterval(intervalId)
            }, 'detectFlowsPolling')
        },

        stopPolling: () => {
            cache.disposables.dispose('detectFlowsPolling')
        },

        dismissBanner: async () => {
            actions.stopStreaming()
            actions.stopPolling()
            try {
                const baseUrl = `api/projects/${getCurrentTeamId()}/agentic_tests/`
                await api.delete(`${baseUrl}detect_flows/`)
            } catch {
                // Best-effort dismiss
            }
        },
    })),

    events(({ actions }) => ({
        afterMount: async () => {
            try {
                const baseUrl = `api/projects/${getCurrentTeamId()}/agentic_tests/`
                const response = await api.get<{
                    task_id: string
                    task_run_id: string
                    status: string | null
                } | null>(`${baseUrl}detect_flows/`)
                if (response?.task_id && response?.task_run_id) {
                    const runStatus = response.status as TaskRunStatus
                    if (isTerminalStatus(runStatus)) {
                        actions.restoreTerminalRun(response.task_id, response.task_run_id, runStatus)
                    } else {
                        actions.restoreActiveRun(response.task_id, response.task_run_id)
                    }
                }
            } catch {
                // 204 No Content or error — no active run, nothing to restore
            }
        },
    })),
])
