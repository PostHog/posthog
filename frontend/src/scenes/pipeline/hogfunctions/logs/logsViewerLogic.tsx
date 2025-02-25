import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { LogEntryLevel } from '~/types'

import type { logsViewerLogicType } from './logsViewerLogicType'

export const ALL_LOG_LEVELS: LogEntryLevel[] = ['DEBUG', 'LOG', 'INFO', 'WARNING', 'ERROR']
export const DEFAULT_LOG_LEVELS: LogEntryLevel[] = ['LOG', 'INFO', 'WARNING', 'ERROR']

export type LogsViewerLogicProps = {
    sourceType: 'hog_function'
    sourceId: string
}

export const LOG_VIEWER_LIMIT = 100

export type GroupedLogEntry = {
    instanceId: string
    maxTimestamp: Dayjs
    minTimestamp: Dayjs
    logLevel: LogEntryLevel
    entries: {
        message: string
        level: LogEntryLevel
        timestamp: Dayjs
    }[]
}

type GroupedLogEntryRequest = {
    sourceType: 'hog_function'
    sourceId: string
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
        AND log_source = '${request.sourceType}'
        AND log_source_id = '${request.sourceId}'
        GROUP BY instance_id
        HAVING countIf(
            lower(level) IN (${request.levels.map((level) => `'${level.toLowerCase()}'`).join(',')})
            AND message ILIKE '%${request.searchTerm}%'
            ${request.before ? `AND timestamp < ${hogql`${request.before}`}` : ''}
            ${request.after ? `AND timestamp > ${hogql`${request.after}`}` : ''}
        ) > 0
        ORDER BY latest_timestamp DESC
        LIMIT ${LOG_VIEWER_LIMIT}`,
    }

    const response = await api.query(query, undefined, undefined, true)

    return response.results.map((result) => ({
        instanceId: result[0],
        maxTimestamp: dayjs(result[1]),
        minTimestamp: dayjs(result[2]),
        entries: result[3].map((entry: any) => ({
            timestamp: dayjs(entry[0]),
            level: entry[1].toUpperCase(),
            message: entry[2],
        })),
    })) as GroupedLogEntry[]
}

const sanitizeGroupedLogs = (groups: GroupedLogEntry[]): GroupedLogEntry[] => {
    const byId: Record<string, GroupedLogEntry> = {}

    for (const group of groups) {
        // Set the group if not already set
        if (!byId[group.instanceId]) {
            byId[group.instanceId] = group
        }

        const highestLogLevel = group.entries.reduce((max, entry) => {
            return Math.max(max, ALL_LOG_LEVELS.indexOf(entry.level))
        }, 0)
        byId[group.instanceId].logLevel = ALL_LOG_LEVELS[highestLogLevel]
    }

    return Object.values(byId).sort((a, b) => b.maxTimestamp.unix() - a.maxTimestamp.unix())
}

export const logsViewerLogic = kea<logsViewerLogicType>([
    path((key) => ['scenes', 'pipeline', 'hogfunctions', 'logs', 'logsViewerLogic', key]),
    props({} as LogsViewerLogicProps), // TODO: Remove `stage` from props, it isn't needed here for anything
    key(({ sourceType, sourceId }) => `${sourceType}:${sourceId}`),
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
                        sourceType: props.sourceType,
                        sourceId: props.sourceId,
                    }
                    const results = await loadGroupedLogs(logParams)
                    return sanitizeGroupedLogs(results)
                },
                loadMoreLogs: async () => {
                    const logParams: GroupedLogEntryRequest = {
                        levels: values.selectedLogLevels,
                        searchTerm: values.searchTerm,
                        sourceType: props.sourceType,
                        sourceId: props.sourceId,
                        before: values.trailingEntryTimestamp ?? undefined,
                    }

                    const results = await loadGroupedLogs(logParams)
                    return sanitizeGroupedLogs([...results, ...values.logs])
                },
                revealBackground: () => {
                    const backgroundLogs = [...values.backgroundLogs]
                    actions.clearBackgroundLogs()
                    return sanitizeGroupedLogs([...backgroundLogs, ...values.logs])
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
                        after: values.leadingEntryTimestamp ?? undefined,
                        sourceType: props.sourceType,
                        sourceId: props.sourceId,
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
                loadLogsSuccess: (_, { logs }) => logs.length >= LOG_VIEWER_LIMIT,
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
    selectors(() => ({
        leadingEntryTimestamp: [
            (s) => [s.logs, s.backgroundLogs],
            (logs: GroupedLogEntry[], backgroundLogs: GroupedLogEntry[]): Dayjs | null => {
                if (backgroundLogs.length) {
                    return backgroundLogs[0].minTimestamp
                }
                if (logs.length) {
                    return logs[0].minTimestamp
                }
                return null
            },
        ],
        trailingEntryTimestamp: [
            (s) => [s.logs, s.backgroundLogs],
            (logs: GroupedLogEntry[], backgroundLogs: GroupedLogEntry[]): Dayjs | null => {
                if (logs.length) {
                    return logs[logs.length - 1].maxTimestamp
                }
                if (backgroundLogs.length) {
                    return backgroundLogs[backgroundLogs.length - 1].maxTimestamp
                }
                return null
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
