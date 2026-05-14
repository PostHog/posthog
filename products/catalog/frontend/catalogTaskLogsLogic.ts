import { actions, afterMount, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { LogEntry, parseLogEvent } from 'products/tasks/frontend/lib/parse-logs'
import { TaskRun, TaskRunStatus } from 'products/tasks/frontend/types'

import type { catalogTaskLogsLogicType } from './catalogTaskLogsLogicType'

const LOG_POLL_INTERVAL_MS = 1000

export interface CatalogTaskLogsLogicProps {
    projectId: string
    taskId: string
    taskRunId: string
}

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
        } else if (line.startsWith('id:')) {
            id = line.slice(3).trim() || null
        } else if (line.startsWith('data:')) {
            data = data ? `${data}\n${line.slice(5).trimStart()}` : line.slice(5).trimStart()
        }
    }
    if (!data && !eventType && !id) {
        return null
    }
    return { data, eventType, id }
}

function buildToolMap(entries: LogEntry[]): Map<string, LogEntry> {
    const m = new Map<string, LogEntry>()
    for (const entry of entries) {
        if (entry.type === 'tool' && entry.toolCallId) {
            m.set(entry.toolCallId, { ...entry })
        }
    }
    return m
}

/** Stripped-down sibling of taskDetailSceneLogic that just loads + streams the
 *  logs for a single (taskId, taskRunId). Catalog logs scene mounts one per
 *  agent task spawned by a CatalogTraversalRun. */
export const catalogTaskLogsLogic = kea<catalogTaskLogsLogicType>([
    path(['products', 'catalog', 'frontend', 'catalogTaskLogsLogic']),
    props({} as CatalogTaskLogsLogicProps),
    key((props) => `${props.taskId}:${props.taskRunId}`),

    actions({
        startStreaming: true,
        stopStreaming: true,
        startPolling: true,
        stopPolling: true,
        markStreamingFailed: true,
        appendStreamEntries: (entries: LogEntry[]) => ({ entries }),
        updateStreamEntries: (entries: LogEntry[]) => ({ entries }),
        recordStreamProgress: (lastEventId: string | null, seenEventIds: string[]) => ({ lastEventId, seenEventIds }),
        setLogs: (logs: string) => ({ logs }),
    }),

    reducers({
        logs: ['' as string, { setLogs: (_, { logs }) => logs }],
        streamEntries: [
            [] as LogEntry[],
            {
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
                    const byId = new Map(entries.map((e) => [e.id, e]))
                    let changed = false
                    const next = state.map((entry) => {
                        const updated = byId.get(entry.id)
                        if (!updated) {
                            return entry
                        }
                        changed = true
                        return updated
                    })
                    return changed ? next : state
                },
            },
        ],
        lastStreamEventId: [
            null as string | null,
            { recordStreamProgress: (state, { lastEventId }) => lastEventId ?? state },
        ],
        seenStreamEventIds: [
            {} as Record<string, true>,
            {
                recordStreamProgress: (state, { seenEventIds }) =>
                    seenEventIds.length === 0
                        ? state
                        : { ...state, ...Object.fromEntries(seenEventIds.map((id) => [id, true])) },
            },
        ],
        isStreaming: [false, { startStreaming: () => true, stopStreaming: () => false }],
        streamingFailed: [false, { markStreamingFailed: () => true }],
    }),

    loaders(({ props }) => ({
        run: [
            null as TaskRun | null,
            {
                loadRun: async () => {
                    return await api.tasks.runs.get(props.taskId, props.taskRunId)
                },
            },
        ],
        rawLogs: [
            '' as string,
            {
                loadLogs: async () => {
                    const url = `/api/projects/${props.projectId}/tasks/${props.taskId}/runs/${props.taskRunId}/logs/`
                    try {
                        const response = await fetch(url, {
                            cache: 'no-store',
                            headers: { 'Cache-Control': 'no-cache' },
                        })
                        if (response.status === 404) {
                            return ''
                        }
                        if (!response.ok) {
                            return ''
                        }
                        return await response.text()
                    } catch {
                        return ''
                    }
                },
            },
        ],
    })),

    selectors({
        shouldPoll: [
            (s) => [s.run],
            (run): boolean =>
                run !== null && (run.status === TaskRunStatus.QUEUED || run.status === TaskRunStatus.IN_PROGRESS),
        ],
    }),

    listeners(({ actions, cache, props, values }) => ({
        loadLogsSuccess: ({ rawLogs }) => {
            if (rawLogs) {
                actions.setLogs(rawLogs)
            }
        },
        loadRunSuccess: () => {
            if (values.shouldPoll) {
                if (values.streamingFailed) {
                    actions.startPolling()
                } else if (!values.isStreaming) {
                    actions.startStreaming()
                }
            } else {
                actions.stopPolling()
                actions.stopStreaming()
            }
        },
        startPolling: () => {
            cache.disposables.add(() => {
                const id = window.setInterval(() => {
                    actions.loadRun()
                    actions.loadLogs()
                }, LOG_POLL_INTERVAL_MS)
                return () => clearInterval(id)
            }, 'polling')
        },
        stopPolling: () => {
            cache.disposables.dispose('polling')
        },
        startStreaming: () => {
            actions.stopPolling()
            cache.disposables.add(() => {
                const abort = new AbortController()
                const streamUrl = `/api/projects/${props.projectId}/tasks/${props.taskId}/runs/${props.taskRunId}/stream/`
                const toolMap = buildToolMap(values.streamEntries)
                let eventIndex = values.streamEntries.length

                const consume = async (): Promise<void> => {
                    try {
                        const response = await fetch(streamUrl, {
                            signal: abort.signal,
                            headers: {
                                Accept: 'text/event-stream',
                                ...(values.lastStreamEventId ? { 'Last-Event-ID': values.lastStreamEventId } : {}),
                            },
                        })
                        if (!response.ok || !response.body) {
                            actions.stopStreaming()
                            actions.markStreamingFailed()
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
                            const updatedById = new Map<string, LogEntry>()
                            let lastProcessedEventId: string | null = null
                            const newlySeen: string[] = []

                            for (const block of blocks) {
                                const parsed = parseSseEventBlock(block)
                                if (!parsed || parsed.eventType === 'keepalive' || !parsed.data) {
                                    continue
                                }
                                if (parsed.id) {
                                    if (values.seenStreamEventIds[parsed.id] || newlySeen.includes(parsed.id)) {
                                        continue
                                    }
                                    newlySeen.push(parsed.id)
                                    lastProcessedEventId = parsed.id
                                }
                                try {
                                    const ev = JSON.parse(parsed.data) as Record<string, unknown>
                                    const entryId = parsed.id ? `stream-${parsed.id}` : `stream-${eventIndex++}`
                                    const entry = parseLogEvent(ev, entryId, toolMap, (u) => {
                                        updatedById.set(u.id, u)
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
                                    // skip
                                }
                            }
                            if (newlySeen.length > 0) {
                                actions.recordStreamProgress(lastProcessedEventId, newlySeen)
                            }
                            if (updatedById.size > 0) {
                                actions.updateStreamEntries(Array.from(updatedById.values()))
                            }
                            if (batch.length > 0) {
                                actions.appendStreamEntries(batch)
                            }
                        }
                        actions.stopStreaming()
                        actions.loadRun()
                    } catch (e) {
                        if ((e as Error).name === 'AbortError') {
                            return
                        }
                        actions.stopStreaming()
                        actions.markStreamingFailed()
                        actions.startPolling()
                    }
                }

                consume()
                return () => abort.abort()
            }, 'stream')
        },
        stopStreaming: () => {
            cache.disposables.dispose('stream')
        },
    })),

    afterMount(({ actions }) => {
        actions.loadRun()
        actions.loadLogs()
    }),

    beforeUnmount(({ actions }) => {
        actions.stopPolling()
        actions.stopStreaming()
    }),
])
