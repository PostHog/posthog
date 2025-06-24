import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'

import { hogql } from '~/queries/utils'
import { LogEntryLevel } from '~/types'

import type { logsViewerLogicType } from './logsViewerLogicType'

export const ALL_LOG_LEVELS: LogEntryLevel[] = ['DEBUG', 'LOG', 'INFO', 'WARNING', 'ERROR']
export const DEFAULT_LOG_LEVELS: LogEntryLevel[] = ['LOG', 'INFO', 'WARNING', 'ERROR']

export type LogsViewerLogicProps = {
    sourceType: 'hog_function' | 'hog_flow'
    sourceId: string
}

export type LogsViewerFilters = {
    levels: LogEntryLevel[]
    search: string
    date_from?: string
    date_to?: string
}

export const LOG_VIEWER_LIMIT = 500

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
    sourceType: 'hog_function' | 'hog_flow'
    sourceId: string
    levels: LogEntryLevel[]
    search: string
    date_from?: string
    date_to?: string
    order: 'ASC' | 'DESC'
}

const loadGroupedLogs = async (request: GroupedLogEntryRequest): Promise<GroupedLogEntry[]> => {
    const query = hogql`
        SELECT
            instance_id,
            max(timestamp) AS latest_timestamp,
            min(timestamp) AS earliest_timestamp,
            arraySort(
                groupArray((timestamp, level, message))
            ) AS messages
        FROM log_entries
        WHERE log_source = ${request.sourceType}
        AND log_source_id = ${request.sourceId}
        AND timestamp > {filters.dateRange.from}
        AND timestamp < {filters.dateRange.to}
        AND instance_id in (
            SELECT DISTINCT instance_id
            FROM log_entries
            WHERE log_source = ${request.sourceType}
            AND log_source_id = ${request.sourceId}
            AND timestamp > {filters.dateRange.from}
            AND timestamp < {filters.dateRange.to}
            AND lower(level) IN (${hogql.raw(request.levels.map((level) => `'${level.toLowerCase()}'`).join(','))})
            AND message ILIKE '%${hogql.raw(request.search)}%'
            ORDER BY timestamp ${hogql.raw(request.order)}
            LIMIT ${LOG_VIEWER_LIMIT}
        )
        GROUP BY instance_id
        ORDER BY latest_timestamp DESC`

    const response = await api.queryHogQL(query, {
        refresh: 'force_blocking',
        filtersOverride: {
            date_from: request.date_from ?? '-7d',
            date_to: request.date_to,
        },
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
        } else {
            // If the group already exists, we need to merge the entries
            for (const entry of group.entries) {
                if (!byId[group.instanceId].entries.find((e) => e.timestamp.isSame(entry.timestamp))) {
                    byId[group.instanceId].entries.push(entry)
                }
            }
        }

        // Sort the entries by timestamp
        byId[group.instanceId].entries.sort((a, b) => a.timestamp.diff(b.timestamp))

        // Go in reverse and find the highest level message

        const highestLogLevel = group.entries.reduce((max, entry) => {
            return Math.max(max, ALL_LOG_LEVELS.indexOf(entry.level))
        }, 0)
        byId[group.instanceId].logLevel = ALL_LOG_LEVELS[highestLogLevel]
    }

    return Object.values(byId).sort((a, b) => b.maxTimestamp.diff(a.maxTimestamp))
}

export const logsViewerLogic = kea<logsViewerLogicType>([
    path((key) => ['scenes', 'pipeline', 'hogfunctions', 'logs', 'logsViewerLogic', key]),
    props({} as LogsViewerLogicProps), // TODO: Remove `stage` from props, it isn't needed here for anything
    key(({ sourceType, sourceId }) => `${sourceType}:${sourceId}`),
    actions({
        setFilters: (filters: Partial<LogsViewerFilters>) => ({ filters }),
        addLogGroups: (logGroups: GroupedLogEntry[]) => ({ logGroups }),
        setHiddenLogs: (logGroups: GroupedLogEntry[]) => ({ logGroups }),
        clearHiddenLogs: true,
        markLogsEnd: true,
        revealHiddenLogs: true,
        setRowExpanded: (instanceId: string, expanded: boolean) => ({ instanceId, expanded }),
        scheduleLoadNewerLogs: true,
        loadLogs: true,
        loadNewerLogs: true,
    }),
    loaders(({ props, values, actions }) => ({
        logs: [
            [] as GroupedLogEntry[],
            {
                loadLogs: async (_, breakpoint) => {
                    await breakpoint(10)

                    actions.clearHiddenLogs()

                    const logParams: GroupedLogEntryRequest = {
                        levels: values.filters.levels,
                        search: values.filters.search,
                        sourceType: props.sourceType,
                        sourceId: props.sourceId,
                        date_from: values.filters.date_from,
                        date_to: values.filters.date_to,
                        order: 'DESC',
                    }
                    const results = await loadGroupedLogs(logParams)

                    await breakpoint(10)

                    return sanitizeGroupedLogs(results)
                },
                loadMoreLogs: async () => {
                    if (!values.oldestLogTimestamp) {
                        return values.logs
                    }
                    const logParams: GroupedLogEntryRequest = {
                        levels: values.filters.levels,
                        search: values.filters.search,
                        sourceType: props.sourceType,
                        sourceId: props.sourceId,
                        date_to: values.oldestLogTimestamp.toISOString(),
                        date_from: values.filters.date_from,
                        order: 'DESC',
                    }

                    const results = await loadGroupedLogs(logParams)

                    if (!results.length) {
                        actions.markLogsEnd()
                    }
                    return sanitizeGroupedLogs([...results, ...values.logs])
                },

                revealHiddenLogs: () => {
                    // We pull out the hidden log groups and add them to the main logs
                    const hiddenLogs = [...values.hiddenLogs]

                    actions.clearHiddenLogs()
                    return sanitizeGroupedLogs([...hiddenLogs, ...values.logs])
                },
                addLogGroups: ({ logGroups }) => {
                    return sanitizeGroupedLogs([...logGroups, ...values.logs])
                },
            },
        ],

        hiddenLogs: [
            [] as GroupedLogEntry[],
            {
                loadNewerLogs: async (_, breakpoint) => {
                    await breakpoint(10)

                    // We load all logs groups that have a timestamp after the newest log timestamp
                    // For ones we already have we just replace them, otherwise we add them to the "hidden" logs list
                    if (!values.newestLogTimestamp) {
                        return values.hiddenLogs
                    }
                    const logParams: GroupedLogEntryRequest = {
                        levels: values.filters.levels,
                        search: values.filters.search,
                        sourceType: props.sourceType,
                        sourceId: props.sourceId,
                        date_from: values.newestLogTimestamp.toISOString(),
                        date_to: values.filters.date_to,
                        order: 'ASC',
                    }

                    const results = await loadGroupedLogs(logParams)

                    await breakpoint(10)

                    const newLogs: GroupedLogEntry[] = []
                    const existingLogsToUpdate: GroupedLogEntry[] = []
                    const existingLogIds = values.logs.map((log) => log.instanceId)

                    if (values.logsLoading) {
                        // TRICKY: Something changed whilst we were doing this query - we don't want to mess with things
                        // so we just exit
                        return values.hiddenLogs
                    }

                    for (const log of results) {
                        if (existingLogIds.includes(log.instanceId)) {
                            // If we already have this log group showing then we can just update it
                            existingLogsToUpdate.push(log)
                        } else {
                            // Otherwise we add it to the list of hidden logs
                            newLogs.push(log)
                        }
                    }

                    if (existingLogsToUpdate.length) {
                        // Update the existing logs with the new data
                        actions.loadLogsSuccess(sanitizeGroupedLogs([...existingLogsToUpdate, ...values.logs]))
                    }

                    actions.scheduleLoadNewerLogs()

                    return sanitizeGroupedLogs([...newLogs, ...values.hiddenLogs])
                },
                clearHiddenLogs: () => [],
            },
        ],
    })),
    reducers({
        filters: [
            {
                search: '',
                levels: DEFAULT_LOG_LEVELS,
                date_from: '-7d',
                date_to: undefined,
            } as LogsViewerFilters,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
            },
        ],
        isThereMoreToLoad: [
            true,
            {
                markLogsEnd: () => false,
                loadLogs: () => true,
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
        newestLogTimestamp: [
            (s) => [s.logs, s.hiddenLogs],
            (logs: GroupedLogEntry[], hiddenLogs: GroupedLogEntry[]): Dayjs | null => {
                return logs.concat(hiddenLogs).reduce((max, log) => {
                    if (!max) {
                        return log.maxTimestamp
                    }
                    return log.maxTimestamp.isAfter(max) ? log.maxTimestamp : max
                }, null as Dayjs | null)
            },
        ],

        oldestLogTimestamp: [
            (s) => [s.logs, s.hiddenLogs],
            (logs: GroupedLogEntry[], hiddenLogs: GroupedLogEntry[]): Dayjs | null => {
                return logs.concat(hiddenLogs).reduce((min, log) => {
                    if (!min) {
                        return log.minTimestamp
                    }
                    return log.minTimestamp.isBefore(min) ? log.minTimestamp : min
                }, null as Dayjs | null)
            },
        ],
    })),
    listeners(({ actions, cache }) => ({
        setFilters: async (_, breakpoint) => {
            await breakpoint(500)
            actions.loadLogs()
        },

        loadLogsSuccess: () => {
            actions.scheduleLoadNewerLogs()
        },

        scheduleLoadNewerLogs: () => {
            if (cache.pollingTimeout) {
                clearTimeout(cache.pollingTimeout)
            }
            cache.pollingTimeout = setTimeout(() => actions.loadNewerLogs(), 5000)
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.loadLogs()
        },
        beforeUnmount: () => {
            clearInterval(cache.pollingTimeout)
        },
    })),
])
