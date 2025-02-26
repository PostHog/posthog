import { lemonToast } from '@posthog/lemon-ui'
import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { LogEntryLevel } from '~/types'

import type { logsViewerLogicType } from './logsViewerLogicType'

export const ALL_LOG_LEVELS: LogEntryLevel[] = ['DEBUG', 'LOG', 'INFO', 'WARNING', 'ERROR']
export const DEFAULT_LOG_LEVELS: LogEntryLevel[] = ['LOG', 'INFO', 'WARNING', 'ERROR']

export type LogsViewerLogicProps = {
    sourceType: 'hog_function'
    sourceId: string
}

export type LogsViewerFilters = {
    levels: LogEntryLevel[]
    search: string
    after?: string
    before?: string
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
    before?: string
    after?: string
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
        WHERE log_source = '${request.sourceType}'
        AND log_source_id = '${request.sourceId}'
        GROUP BY instance_id
        HAVING countIf(
            lower(level) IN (${request.levels.map((level) => `'${level.toLowerCase()}'`).join(',')})
            AND message ILIKE '%${request.searchTerm}%'
            AND timestamp >= {filters.dateRange.from}
            AND timestamp <= {filters.dateRange.to}
        ) > 0
        ORDER BY latest_timestamp DESC
        LIMIT ${LOG_VIEWER_LIMIT}`,
    }

    const response = await api.query(query, undefined, undefined, true, {
        date_from: request.after ?? '-7d',
        date_to: request.before,
    })

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

        // Go in reverse and find the highest level message

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
        setFilters: (filters: Partial<LogsViewerFilters>) => ({ filters }),
        addLogGroups: (logGroups: GroupedLogEntry[]) => ({ logGroups }),
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
                        levels: values.filters.levels,
                        searchTerm: values.filters.search,
                        sourceType: props.sourceType,
                        sourceId: props.sourceId,
                        before: values.filters.before,
                        after: values.filters.after,
                    }
                    const results = await loadGroupedLogs(logParams)
                    return sanitizeGroupedLogs(results)
                },
                loadMoreLogs: async () => {
                    if (!values.trailingEntryTimestamp) {
                        lemonToast.warning('No more logs to load')
                        return values.logs
                    }
                    const logParams: GroupedLogEntryRequest = {
                        levels: values.filters.levels,
                        searchTerm: values.filters.search,
                        sourceType: props.sourceType,
                        sourceId: props.sourceId,
                        before: values.trailingEntryTimestamp.toISOString(),
                        after: values.filters.after,
                    }

                    const results = await loadGroupedLogs(logParams)
                    return sanitizeGroupedLogs([...results, ...values.logs])
                },
                revealBackground: () => {
                    const backgroundLogs = [...values.backgroundLogs]
                    actions.clearBackgroundLogs()
                    return sanitizeGroupedLogs([...backgroundLogs, ...values.logs])
                },
                addLogGroups: ({ logGroups }) => {
                    return sanitizeGroupedLogs([...logGroups, ...values.logs])
                },
            },
        ],
        backgroundLogs: [
            [] as GroupedLogEntry[],
            {
                pollBackgroundLogs: async () => {
                    if (!values.leadingEntryTimestamp) {
                        return []
                    }
                    const logParams: GroupedLogEntryRequest = {
                        searchTerm: values.filters.search,
                        levels: values.filters.levels,
                        after: values.leadingEntryTimestamp.toISOString(),
                        before: values.filters.before,
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
        filters: [
            {
                search: '',
                levels: DEFAULT_LOG_LEVELS,
                after: '-7d',
                before: undefined,
            } as LogsViewerFilters,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
            },
        ],
        backgroundLogs: [
            [] as GroupedLogEntry[],
            {
                clearBackgroundLogs: () => [],
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
    })),
    listeners(({ actions }) => ({
        setFilters: async (_, breakpoint) => {
            await breakpoint(500)
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
