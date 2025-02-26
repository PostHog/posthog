import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { beforeUnload } from 'kea-router'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { LogEntryLevel } from '~/types'

import type { hogFunctionLogsLogicType } from './hogFunctionLogsLogicType'
import { GroupedLogEntry, logsViewerLogic, LogsViewerLogicProps } from './logsViewerLogic'

export type RetryInvocationState = 'pending' | 'success' | 'failure'

const eventIdMatchers = [/Event: ([A-Za-z0-9-]+)/, /\/events\/([A-Za-z0-9-]+)\//, /event ([A-Za-z0-9-]+)/]

async function runWithParallelism<T, R>(
    items: T[],
    maxParallel: number,
    asyncFn: (item: T) => Promise<R>
): Promise<R[]> {
    const results: R[] = []
    const executing = new Set<Promise<void>>()

    for (const item of items) {
        const promise = (async () => {
            const result = await asyncFn(item)
            results.push(result)
        })()

        executing.add(promise)
        void promise.finally(() => executing.delete(promise))

        if (executing.size >= maxParallel) {
            await Promise.race(executing)
        }
    }

    await Promise.all(executing)
    return results
}

const loadClickhouseEvents = async (eventIds: string[]): Promise<any[]> => {
    const query: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: `
            select uuid, distinct_id, event, timestamp, properties, elements_chain, person.id, person.properties, person.created_at 
            from events
            where uuid in (${eventIds.map((x) => `'${x}'`).join(',')})`,
    }

    const response = await api.query(query, undefined, undefined, true)

    return response.results.map((x) => {
        const [
            uuid,
            distinct_id,
            event,
            timestamp,
            properties,
            elements_chain,
            person_id,
            person_properties,
            person_created_at,
        ] = x

        return {
            uuid,
            event,
            distinct_id,
            person_id,
            timestamp,
            properties,
            elements_chain,
            person_created_at,
            person_properties,
        }
    })
}

export const hogFunctionLogsLogic = kea<hogFunctionLogsLogicType>([
    path((key) => ['scenes', 'pipeline', 'hogfunctions', 'logs', 'hogFunctionLogsLogic', key]),
    props({} as LogsViewerLogicProps), // TODO: Remove `stage` from props, it isn't needed here for anything
    key(({ sourceType, sourceId }) => `${sourceType}:${sourceId}`),
    connect((props: LogsViewerLogicProps) => ({
        values: [logsViewerLogic(props), ['logs']],
        actions: [logsViewerLogic(props), ['addLogGroups', 'setRowExpanded']],
    })),
    actions({
        setSelectingMany: (selectingMany: boolean) => ({ selectingMany }),
        setSelectedForRetry: (selectedForRetry: Record<string, boolean>) => ({ selectedForRetry }),
        selectAllForRetry: true,
        retryInvocation: (groupedLogEntry: GroupedLogEntry, eventId: string) => ({ groupedLogEntry, eventId }),
        retryInvocations: (groupedLogEntries: GroupedLogEntry[]) => ({ groupedLogEntries }),
        retryInvocationStarted: (groupedLogEntry: GroupedLogEntry) => ({ groupedLogEntry }),
        retryInvocationSuccess: (groupedLogEntry: GroupedLogEntry) => ({ groupedLogEntry }),
        retryInvocationFailure: (groupedLogEntry: GroupedLogEntry) => ({ groupedLogEntry }),
        retrySelectedInvocations: true,
    }),
    reducers({
        selectingMany: [
            false,
            {
                setSelectingMany: (_, { selectingMany }) => selectingMany,
            },
        ],

        selectedForRetry: [
            {} as Record<string, boolean>,
            {
                setSelectedForRetry: (state, { selectedForRetry }) => {
                    const newState = { ...state }
                    Object.keys(selectedForRetry).forEach((key) => {
                        newState[key] = selectedForRetry[key]

                        if (!selectedForRetry[key]) {
                            delete newState[key]
                        }
                    })
                    return newState
                },

                setSelectingMany: (state, { selectingMany }) => {
                    return selectingMany ? state : {}
                },
            },
        ],

        retries: [
            {} as Record<string, RetryInvocationState>,
            {
                retryInvocationStarted: (state, { groupedLogEntry }) => {
                    return {
                        ...state,
                        [groupedLogEntry.instanceId]: 'pending',
                    }
                },

                retryInvocationSuccess: (state, { groupedLogEntry }) => {
                    return {
                        ...state,
                        [groupedLogEntry.instanceId]: 'success',
                    }
                },

                retryInvocationFailure: (state, { groupedLogEntry }) => {
                    return {
                        ...state,
                        [groupedLogEntry.instanceId]: 'failure',
                    }
                },
            },
        ],
    }),

    selectors({
        retryRunning: [
            (s) => [s.retries],
            (retries) => {
                return Object.values(retries).some((x) => x === 'pending')
            },
        ],

        eventIdByInvocationId: [
            (s) => [s.logs],
            (logs) => {
                const eventIdByInvocationId: Record<string, string> = {}

                for (const record of logs) {
                    // TRICKY: We have the event ID in different places in different logs. We will standardise this to be the invocation ID in the future.
                    const entryContainingEventId = record.entries.find(
                        (entry) =>
                            entry.message.includes('Function completed') ||
                            entry.message.includes('Suspending function') ||
                            entry.message.includes('Error executing function on event')
                    )

                    if (!entryContainingEventId) {
                        return undefined
                    }

                    for (const matcher of eventIdMatchers) {
                        const match = entryContainingEventId.message.match(matcher)
                        if (match) {
                            eventIdByInvocationId[record.instanceId] = match[1]
                            break
                        }
                    }
                }

                return eventIdByInvocationId
            },
        ],
    }),
    listeners(({ actions, props, values }) => ({
        retryInvocations: async ({ groupedLogEntries }) => {
            await lemonToast.promise(
                (async () => {
                    for (const groupedLogEntry of groupedLogEntries) {
                        actions.retryInvocationStarted(groupedLogEntry)
                    }

                    // Load all events by ID
                    const events = await loadClickhouseEvents(Object.values(values.eventIdByInvocationId ?? {}))

                    const eventsById: Record<string, any> = {}
                    for (const event of events) {
                        eventsById[event.uuid] = event
                    }

                    await runWithParallelism(groupedLogEntries, 10, async (groupedLogEntry) => {
                        console.log('RUNNING!')
                        try {
                            // If we have an event then retry it, otherwise fail
                            const event = eventsById[values.eventIdByInvocationId![groupedLogEntry.instanceId]]

                            if (!event) {
                                actions.retryInvocationFailure(groupedLogEntry)
                                return
                            }

                            const res = await api.hogFunctions.createTestInvocation(props.sourceId, {
                                clickhouse_event: event,
                                mock_async_functions: false,
                                configuration: {
                                    // For retries we don't care about filters
                                    filters: {},
                                },
                                invocation_id: groupedLogEntry.instanceId,
                            })

                            const newLogGroup: GroupedLogEntry = {
                                ...groupedLogEntry,
                                entries: [
                                    ...groupedLogEntry.entries,
                                    ...res.logs.map((x) => ({
                                        timestamp: dayjs(x.timestamp),
                                        level: x.level.toUpperCase() as LogEntryLevel,
                                        message: x.message,
                                    })),
                                ],
                            }

                            actions.addLogGroups([newLogGroup])
                            actions.retryInvocationSuccess(groupedLogEntry)
                        } catch (e) {
                            actions.retryInvocationFailure(groupedLogEntry)
                        }
                        console.log('DONE!')
                    })

                    actions.setSelectingMany(false)
                })(),
                {
                    success: 'Retries complete!',
                    error: 'Retry failed!',
                    pending: 'Retrying...',
                }
            )
        },

        retrySelectedInvocations: async () => {
            const groupsToRetry = values.logs.filter((x) => values.selectedForRetry[x.instanceId])

            actions.retryInvocations(groupsToRetry)
        },

        selectAllForRetry: async () => {
            actions.setSelectingMany(true)

            for (const groupedLogEntry of values.logs) {
                actions.setSelectedForRetry({
                    [groupedLogEntry.instanceId]: true,
                })
            }
        },
    })),

    beforeUnload(({ values, cache }) => ({
        enabled: () => !cache.disabledBeforeUnload && values.retryRunning,
        message: 'You have running retries that will be discarded if you leave. Are you sure?',
        onConfirm: () => {
            cache.disabledBeforeUnload = true
        },
    })),
])
