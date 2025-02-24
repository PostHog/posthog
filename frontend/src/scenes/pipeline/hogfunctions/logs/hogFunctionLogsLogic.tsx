import { LemonTableColumns, Link } from '@posthog/lemon-ui'
import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { LogEntry, LogEntryLevel } from '~/types'

import type { hogFunctionLogsLogicType } from './hogFunctionLogsLogicType'

export const ALL_LOG_LEVELS: LogEntryLevel[] = ['DEBUG', 'LOG', 'INFO', 'WARNING', 'ERROR']
export const DEFAULT_LOG_LEVELS: LogEntryLevel[] = ['LOG', 'INFO', 'WARNING', 'ERROR']

export type HogFunctionLogsProps = {
    id: string
}

export type GroupedLogEntry = {
    instanceId: string
    timestamp: string
    entries: {
        message: string
        level: LogEntryLevel
        timestamp: string
    }[]
}

export const HogFunctionLogsLimit = 100

type GroupedLogEntryRequest = {
    hogFunctionId: string
    levels: LogEntryLevel[]
    searchTerm: string
    before: string | null
}

const loadGroupedLogs = async (request: GroupedLogEntryRequest): Promise<GroupedLogEntry[]> => {
    const query: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: hogql`SELECT
            instance_id,
            max(timestamp) AS latest_timestamp,
            arraySort(
                groupArray((timestamp, level, message))
            ) AS messages
        FROM log_entries
        WHERE timestamp >= now() - INTERVAL 1 DAY  -- Adjust time range as needed
        AND log_source = 'hog_function'
        AND log_source_id = ${request.hogFunctionId}
        GROUP BY instance_id
        HAVING countIf(lower(level) IN ${request.levels.map((level) => level.toLowerCase())}) > 0
        ORDER BY instance_id`,
    }

    const response = await api.query(query, undefined, undefined, true)

    return response.results.map((result) => ({
        instanceId: result[0],
        timestamp: result[1],
        entries: result[2].map((entry: any) => ({
            timestamp: entry[0],
            level: entry[1],
            message: entry[2],
        })),
    })) as GroupedLogEntry[]
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
    }),
    loaders(({ props, values, actions, cache }) => ({
        logs: [
            [] as GroupedLogEntry[],
            {
                loadLogs: async () => {
                    if (!cache.pollingInterval) {
                        cache.pollingInterval = setInterval(actions.pollBackgroundLogs, 5000)
                    }
                    actions.clearBackgroundLogs()

                    const logParams: GroupedLogEntryRequest = {
                        levels: values.selectedLogLevels,
                        searchTerm: values.searchTerm,
                        before: values.trailingEntry?.timestamp,
                        hogFunctionId: props.id,
                    }
                    const results = await loadGroupedLogs(logParams)
                    return results
                },
                // loadMoreLogs: async () => {
                //     const logParams: LogEntryRequestParams = {
                //         search: values.searchTerm,
                //         level: values.selectedLogLevels.join(','),
                //         limit: LOGS_PORTION_LIMIT,
                //         before: values.trailingEntry?.timestamp,
                //         instance_id: values.instanceId ?? undefined,
                //     }
                //     const results = await loadGroupedLogs(values.selectedLogLevels)

                //     return [...values.logs]
                // },
                // revealBackground: () => {
                //     const newArray = [...values.backgroundLogs, ...values.logs]
                //     actions.clearBackgroundLogs()
                //     return newArray
                // },
            },
        ],
        backgroundLogs: [
            [] as GroupedLogEntry[],
            {
                pollBackgroundLogs: async () => {
                    return [...values.backgroundLogs]
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
            [] as LogEntry[],
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
                loadLogsSuccess: (_, { logs }) => logs.length >= HogFunctionLogsLimit,
                markLogsEnd: () => false,
            },
        ],
    }),
    selectors(({ actions, values }) => ({
        leadingEntry: [
            (s) => [s.logs, s.backgroundLogs],
            (logs: GroupedLogEntry[], backgroundLogs: GroupedLogEntry[]): GroupedLogEntry | null => {
                if (backgroundLogs.length) {
                    return backgroundLogs[0]
                }
                if (logs.length) {
                    return logs[0]
                }
                return null
            },
        ],
        trailingEntry: [
            (s) => [s.logs, s.backgroundLogs],
            (logs: GroupedLogEntry[], backgroundLogs: GroupedLogEntry[]): GroupedLogEntry | null => {
                if (logs.length) {
                    return logs[logs.length - 1]
                }
                if (backgroundLogs.length) {
                    return backgroundLogs[backgroundLogs.length - 1]
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
            (logLevels): LogEntryLevel[] => {
                const uniqueLevels = new Set(logLevels)
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
