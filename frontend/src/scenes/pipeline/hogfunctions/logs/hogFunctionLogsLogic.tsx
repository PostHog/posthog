import { LemonTableColumns, Link } from '@posthog/lemon-ui'
import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { TZLabel } from 'lib/components/TZLabel'
import { Dayjs, dayjs } from 'lib/dayjs'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { LogEntryLevel } from '~/types'

import type { hogFunctionLogsLogicType } from './hogFunctionLogsLogicType'

export const ALL_LOG_LEVELS: LogEntryLevel[] = ['DEBUG', 'LOG', 'INFO', 'WARNING', 'ERROR']
export const DEFAULT_LOG_LEVELS: LogEntryLevel[] = ['LOG', 'INFO', 'WARNING', 'ERROR']

export type HogFunctionLogsProps = {
    id: string
}

export type GroupedLogEntry = {
    instanceId: string
    maxTimestamp: string
    minTimestamp: string
    logLevel: LogEntryLevel
    entries: {
        message: string
        level: LogEntryLevel
        timestamp: string
    }[]
}

export const HOG_FUNCTION_LOGS_LIMIT = 100

type GroupedLogEntryRequest = {
    hogFunctionId: string
    levels: LogEntryLevel[]
    searchTerm: string
    before?: Dayjs
    after?: Dayjs
}

const loadGroupedLogs = async (request: GroupedLogEntryRequest): Promise<GroupedLogEntry[]> => {
    const query: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: `SELECT
            instance_id,
            max(timestamp) AS latest_timestamp,
            min(timestamp) AS earliest_timestamp,
            arraySort(
                groupArray((timestamp, level, message))
            ) AS messages
        FROM log_entries
        WHERE timestamp >= now() - INTERVAL 1 DAY
        AND log_source = 'hog_function'
        AND log_source_id = '${request.hogFunctionId}'
        GROUP BY instance_id
        HAVING countIf(
            lower(level) IN (${request.levels.map((level) => `'${level.toLowerCase()}'`).join(',')})
            AND message ILIKE '%${request.searchTerm}%'
            ${request.before ? `AND timestamp < ${hogql`${request.before}`}` : ''}
            ${request.after ? `AND timestamp > ${hogql`${request.after}`}` : ''}
        ) > 0
        ORDER BY latest_timestamp DESC
        LIMIT ${HOG_FUNCTION_LOGS_LIMIT}`,
    }

    const response = await api.query(query, undefined, undefined, true)

    return response.results.map((result) => ({
        instanceId: result[0],
        maxTimestamp: result[1],
        minTimestamp: result[2],
        entries: result[3].map((entry: any) => ({
            timestamp: entry[0],
            level: entry[1],
            message: entry[2],
        })),
    })) as GroupedLogEntry[]
}

const dedupeGroupedLogs = (groups: GroupedLogEntry[], newGroups: GroupedLogEntry[] = []): GroupedLogEntry[] => {
    // NOTE: When we are loading new or older logs we might have some crossover of groups so we want to dedupe here
    // Any newLogs that are already in the existing logs should just be appended to the existing logs

    // Store the existing logs by instanceId
    const existingLogsById: Record<string, GroupedLogEntry> = {}
    for (const group of groups) {
        existingLogsById[group.instanceId] = group
    }

    for (const group of newGroups) {
        if (!existingLogsById[group.instanceId]) {
            // For each new log group if there is no existing log group with the same instanceId, add it to the existing logs
            existingLogsById[group.instanceId] = group
        } else {
            // Otherwise add the messages to the existing log group
            existingLogsById[group.instanceId].entries = group.entries
            existingLogsById[group.instanceId].maxTimestamp = group.maxTimestamp
            existingLogsById[group.instanceId].minTimestamp = group.minTimestamp
        }
    }

    return Object.values(existingLogsById).sort((a, b) => dayjs(b.maxTimestamp).unix() - dayjs(a.maxTimestamp).unix())
}

export const hogFunctionLogsLogic = kea<hogFunctionLogsLogicType>([
    path((key) => ['scenes', 'pipeline', 'hogfunctions', 'logs', 'hogFunctionLogsLogic', key]),
    props({} as HogFunctionLogsProps), // TODO: Remove `stage` from props, it isn't needed here for anything
    key(({ id }) => id),
    actions({
        setSelectedLogLevels: (levels: LogEntryLevel[]) => ({
            levels,
        }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setInstanceId: (instanceId: string | null) => ({ instanceId }),
        clearBackgroundLogs: true,
        markLogsEnd: true,
        setRowExpanded: (instanceId: string, expanded: boolean) => ({ instanceId, expanded }),
    }),
    loaders(({ props, values, actions, cache }) => ({
        logs: [
            [] as GroupedLogEntry[],
            {
                loadLogs: async () => {
                    if (!cache.pollingInterval) {
                        cache.pollingInterval = setInterval(() => actions.pollBackgroundLogs(), 5000)
                    }
                    actions.clearBackgroundLogs()

                    const logParams: GroupedLogEntryRequest = {
                        levels: values.selectedLogLevels,
                        searchTerm: values.searchTerm,
                        hogFunctionId: props.id,
                    }
                    const results = await loadGroupedLogs(logParams)
                    return dedupeGroupedLogs(results)
                },
                loadMoreLogs: async () => {
                    const logParams: GroupedLogEntryRequest = {
                        levels: values.selectedLogLevels,
                        searchTerm: values.searchTerm,
                        hogFunctionId: props.id,
                        before: values.trailingEntryTimestamp ?? null,
                    }

                    const results = await loadGroupedLogs(logParams)
                    return dedupeGroupedLogs(values.logs, results)
                },
                revealBackground: () => {
                    const backgroundLogs = [...values.backgroundLogs]
                    actions.clearBackgroundLogs()
                    return dedupeGroupedLogs(values.logs, backgroundLogs)
                },
            },
        ],
        backgroundLogs: [
            [] as GroupedLogEntry[],
            {
                pollBackgroundLogs: async () => {
                    const logParams: GroupedLogEntryRequest = {
                        searchTerm: values.searchTerm,
                        levels: values.selectedLogLevels,
                        after: values.leadingEntryTimestamp ?? null,
                        hogFunctionId: props.id,
                    }

                    const results = await loadGroupedLogs(logParams)

                    return results
                },
            },
        ],
    })),
    reducers({
        selectedLogLevels: [
            DEFAULT_LOG_LEVELS,
            {
                setSelectedLogLevels: (_, { levels }) => levels,
            },
        ],
        backgroundLogs: [
            [] as GroupedLogEntry[],
            {
                clearBackgroundLogs: () => [],
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        instanceId: [
            null as null | string,
            {
                setInstanceId: (_, { instanceId }) => instanceId,
            },
        ],
        isThereMoreToLoad: [
            true,
            {
                loadLogsSuccess: (_, { logs }) => logs.length >= HOG_FUNCTION_LOGS_LIMIT,
                markLogsEnd: () => false,
            },
        ],
        expandedRows: [
            {} as Record<string, boolean>,
            {
                setRowExpanded: (state, { instanceId, expanded }) => ({
                    ...state,
                    [instanceId]: expanded,
                }),
            },
        ],
    }),
    selectors(({ actions, values }) => ({
        leadingEntryTimestamp: [
            (s) => [s.logs, s.backgroundLogs],
            (logs: GroupedLogEntry[], backgroundLogs: GroupedLogEntry[]): Dayjs | null => {
                if (backgroundLogs.length) {
                    return dayjs(backgroundLogs[0].minTimestamp)
                }
                if (logs.length) {
                    return dayjs(logs[0].minTimestamp)
                }
                return null
            },
        ],
        trailingEntryTimestamp: [
            (s) => [s.logs, s.backgroundLogs],
            (logs: GroupedLogEntry[], backgroundLogs: GroupedLogEntry[]): Dayjs | null => {
                if (logs.length) {
                    return dayjs(logs[logs.length - 1].maxTimestamp)
                }
                if (backgroundLogs.length) {
                    return dayjs(backgroundLogs[backgroundLogs.length - 1].maxTimestamp)
                }
                return null
            },
        ],
        columns: [
            () => [],
            (): LemonTableColumns<GroupedLogEntry> => {
                return [
                    {
                        title: 'Timestamp',
                        key: 'timestamp',
                        dataIndex: 'timestamp',
                        sorter: (a: GroupedLogEntry, b: GroupedLogEntry) =>
                            dayjs(a.timestamp).unix() - dayjs(b.timestamp).unix(),
                        render: (timestamp: string) => <TZLabel time={timestamp} />,
                        width: 0,
                    },
                    {
                        width: 0,
                        title: 'Invocation',
                        dataIndex: 'instanceId',
                        key: 'instanceId',
                        render: (instanceId: string) => (
                            <code className="whitespace-nowrap">
                                <Link
                                    subtle
                                    onClick={() => {
                                        if (values.instanceId === instanceId) {
                                            actions.setInstanceId(null)
                                        } else {
                                            actions.setInstanceId(instanceId)
                                        }
                                    }}
                                >
                                    {instanceId}
                                </Link>
                            </code>
                        ),
                    },
                    {
                        title: 'Messages',
                        key: 'entries',
                        dataIndex: 'entries',
                        render: (entries: { message: string; level: LogEntryLevel; timestamp: string }[]) => {
                            const lastEntry = entries[entries.length - 1]
                            return <code className="whitespace-pre-wrap">{lastEntry.message}</code>
                        },
                    },
                ] as LemonTableColumns<GroupedLogEntry>
            },
        ],

        selectedLogLevelsForAPI: [
            (s) => [s.selectedLogLevels],
            (logLevels: LogEntryLevel[]): LogEntryLevel[] => {
                const uniqueLevels = new Set<LogEntryLevel>(logLevels)
                if (uniqueLevels.has('WARN')) {
                    uniqueLevels.add('WARNING')
                }
                if (uniqueLevels.has('WARNING')) {
                    uniqueLevels.add('WARN')
                }
                return Array.from(uniqueLevels)
            },
        ],
    })),
    listeners(({ actions }) => ({
        setSelectedLogLevels: () => {
            actions.loadLogs()
        },
        setSearchTerm: async ({ searchTerm }, breakpoint) => {
            if (searchTerm) {
                await breakpoint(1000)
            }
            actions.loadLogs()
        },
        setInstanceId: async () => {
            actions.loadLogs()
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.loadLogs()
        },
        beforeUnmount: () => {
            clearInterval(cache.pollingInterval)
        },
    })),
])
