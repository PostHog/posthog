import { actions, events, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'

import { HogQLQueryString, hogql } from '~/queries/utils'
import { LogEntryLevel } from '~/types'

import type { logsViewerLogicType } from './logsViewerLogicType'

export const ALL_LOG_LEVELS: LogEntryLevel[] = ['DEBUG', 'LOG', 'INFO', 'WARNING', 'ERROR']
export const DEFAULT_LOG_LEVELS: LogEntryLevel[] = ['DEBUG', 'LOG', 'INFO', 'WARNING', 'ERROR']

export type LogsViewerLogicProps = {
    logicKey?: string
    sourceType: 'hog_function' | 'hog_flow'
    sourceId: string
    groupByInstanceId?: boolean
    searchGroups?: string[]
    // Add forced search params
}

export type LogsViewerFilters = {
    levels: LogEntryLevel[]
    search: string
    date_from?: string
    date_to?: string
}

export const LOG_VIEWER_LIMIT = 500

export type LogEntry = {
    message: string
    instanceId: string
    level: LogEntryLevel
    timestamp: Dayjs
}

export type GroupedLogEntry = {
    instanceId: string
    maxTimestamp: Dayjs
    minTimestamp: Dayjs
    logLevel: LogEntryLevel
    entries: LogEntry[]
}

type LogEntryParams = {
    sourceType: 'hog_function' | 'hog_flow'
    sourceId: string
    levels: LogEntryLevel[]
    searchGroups: string[]
    date_from?: string
    date_to?: string
    order: 'ASC' | 'DESC'
    groupByInstanceId: boolean
}

const buildBoundaryFilters = (request: LogEntryParams): string => {
    return hogql`
        AND log_source = ${request.sourceType}
        AND log_source_id = ${request.sourceId}
        AND timestamp > {filters.dateRange.from}
        AND timestamp < {filters.dateRange.to}
    `
}

const buildSearchFilters = ({ searchGroups, levels }: LogEntryParams): string => {
    let query = hogql`\nAND lower(level) IN (${hogql.raw(levels.map((level) => `'${level.toLowerCase()}'`).join(','))})`

    searchGroups.forEach((search) => {
        query = (query + hogql`\nAND message ILIKE '%${hogql.raw(search)}%'`) as HogQLQueryString
    })

    return query
}

const loadLogs = async (request: LogEntryParams): Promise<LogEntry[]> => {
    const query = hogql`
        SELECT instance_id, timestamp, level, message
        FROM log_entries
        WHERE 1=1
        ${hogql.raw(buildBoundaryFilters(request))}
        ${hogql.raw(buildSearchFilters(request))}
        ORDER BY timestamp ${hogql.raw(request.order)}
        LIMIT ${LOG_VIEWER_LIMIT}`

    const response = await api.queryHogQL(query, {
        refresh: 'force_blocking',
        filtersOverride: {
            date_from: request.date_from ?? '-7d',
            date_to: request.date_to,
        },
    })

    return response.results.map((result) => ({
        instanceId: result[0],
        timestamp: dayjs(result[1]),
        level: result[2].toUpperCase(),
        message: result[3],
    })) as LogEntry[]
}

const loadGroupedLogs = async (request: LogEntryParams): Promise<GroupedLogEntry[]> => {
    if (!request.groupByInstanceId) {
        // NOTE: This looks odd but it allows us to simplify all of our loading logic to support
        // both grouped and non-grouped logs
        const nonGroupedLogs = await loadLogs(request)
        return [
            {
                instanceId: 'all',
                maxTimestamp: dayjs(nonGroupedLogs[0].timestamp),
                minTimestamp: dayjs(nonGroupedLogs[nonGroupedLogs.length - 1].timestamp),
                logLevel: nonGroupedLogs[nonGroupedLogs.length - 1].level,
                entries: nonGroupedLogs,
            },
        ]
    }

    const query = hogql`
        SELECT
            instance_id,
            max(timestamp) AS latest_timestamp,
            min(timestamp) AS earliest_timestamp,
            arraySort(
                groupArray((timestamp, level, message))
            ) AS messages
        FROM log_entries
        WHERE 1=1 
        ${hogql.raw(buildBoundaryFilters(request))}
        AND instance_id in (
            SELECT DISTINCT instance_id
            FROM log_entries
            WHERE 1=1
            ${hogql.raw(buildBoundaryFilters(request))}
            ${hogql.raw(buildSearchFilters(request))}
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
            instanceId: result[0],
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
    key(({ sourceType, sourceId, logicKey }) => logicKey || `${sourceType}:${sourceId}`),
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
        clearLogs: true,
        setIsGrouped: (isGrouped: boolean) => ({ isGrouped }),
    }),
    reducers(({ props }) => ({
        isGrouped: [
            props.groupByInstanceId ?? true,
            {
                setIsGrouped: (_, { isGrouped }) => isGrouped,
            },
        ],
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

        unGroupedLogs: [
            [] as LogEntry[],
            {
                clearLogs: () => [],
            },
        ],
        groupedLogs: [
            [] as GroupedLogEntry[],
            {
                clearLogs: () => [],
            },
        ],
    })),
    loaders(({ values, actions }) => ({
        unGroupedLogs: [
            [] as LogEntry[],
            {
                loadUngroupedLogs: async () => {
                    return await loadLogs(values.logEntryParams)
                },
                loadMoreUngroupedLogs: async () => {
                    return await loadLogs(values.logEntryParams)
                },
            },
        ],
        groupedLogs: [
            [] as GroupedLogEntry[],
            {
                loadGroupedLogs: async (_, breakpoint) => {
                    await breakpoint(10)

                    actions.clearHiddenLogs()
                    const results = await loadGroupedLogs(values.logEntryParams).catch((e) => {
                        lemonToast.error('Error loading logs ' + e.message)
                        throw e
                    })
                    await breakpoint(10)

                    return sanitizeGroupedLogs(results)
                },
                loadMoreGroupedLogs: async () => {
                    if (!values.oldestLogTimestamp) {
                        return values.groupedLogs
                    }
                    const logParams: LogEntryParams = {
                        ...values.logEntryParams,
                        date_to: values.oldestLogTimestamp.toISOString(),
                    }

                    const results = await loadGroupedLogs(logParams)

                    if (!results.length) {
                        actions.markLogsEnd()
                    }
                    return sanitizeGroupedLogs([...results, ...values.groupedLogs])
                },

                revealHiddenLogs: () => {
                    // We pull out the hidden log groups and add them to the main logs
                    const hiddenLogs = [...values.hiddenLogs]

                    actions.clearHiddenLogs()
                    return sanitizeGroupedLogs([...hiddenLogs, ...values.groupedLogs])
                },
                addLogGroups: ({ logGroups }) => {
                    return sanitizeGroupedLogs([...logGroups, ...values.groupedLogs])
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
                    const logParams: LogEntryParams = {
                        ...values.logEntryParams,
                        date_from: values.newestLogTimestamp.toISOString(),
                        order: 'ASC',
                    }

                    const results = await loadGroupedLogs(logParams)

                    await breakpoint(10)

                    const newLogs: GroupedLogEntry[] = []
                    const existingLogsToUpdate: GroupedLogEntry[] = []
                    const existingLogIds = values.groupedLogs.map((log) => log.instanceId)

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
                        actions.loadGroupedLogsSuccess(
                            sanitizeGroupedLogs([...existingLogsToUpdate, ...values.groupedLogs])
                        )
                    }

                    actions.scheduleLoadNewerLogs()

                    return sanitizeGroupedLogs([...newLogs, ...values.hiddenLogs])
                },
                clearHiddenLogs: () => [],
            },
        ],
    })),
    selectors(() => ({
        logsLoading: [
            (s) => [s.groupedLogsLoading, s.unGroupedLogsLoading],
            (groupedLogsLoading, unGroupedLogsLoading): boolean => {
                return groupedLogsLoading || unGroupedLogsLoading
            },
        ],
        newestLogTimestamp: [
            (s) => [s.groupedLogs, s.hiddenLogs],
            (groupedLogs, hiddenLogs): Dayjs | null => {
                return groupedLogs.concat(hiddenLogs).reduce(
                    (max, log) => {
                        if (!max) {
                            return log.maxTimestamp
                        }
                        return log.maxTimestamp.isAfter(max) ? log.maxTimestamp : max
                    },
                    null as Dayjs | null
                )
            },
        ],

        oldestLogTimestamp: [
            (s) => [s.groupedLogs, s.hiddenLogs],
            (groupedLogs, hiddenLogs): Dayjs | null => {
                return groupedLogs.concat(hiddenLogs).reduce(
                    (min, log) => {
                        if (!min) {
                            return log.minTimestamp
                        }
                        return log.minTimestamp.isBefore(min) ? log.minTimestamp : min
                    },
                    null as Dayjs | null
                )
            },
        ],

        logEntryParams: [
            (s) => [(_, p) => p, s.filters, s.isGrouped],
            (props, filters, isGrouped): LogEntryParams => {
                const searchGroups = [filters.search, ...(props.searchGroups || [])].filter((x) => !!x) as string[]
                return {
                    levels: filters.levels,
                    searchGroups: searchGroups,
                    sourceType: props.sourceType,
                    sourceId: props.sourceId,
                    date_from: filters.date_from,
                    date_to: filters.date_to,
                    order: 'DESC',
                    groupByInstanceId: isGrouped,
                }
            },
        ],
    })),
    propsChanged(({ props, actions }, oldProps) => {
        if (props.groupByInstanceId !== oldProps.groupByInstanceId) {
            actions.setIsGrouped(props.groupByInstanceId ?? true)
        }
    }),
    listeners(({ actions, cache, values }) => ({
        loadLogs: () => {
            if (values.isGrouped) {
                actions.loadGroupedLogs()
            } else {
                actions.loadUngroupedLogs()
            }
        },
        loadMoreLogs: () => {
            if (values.isGrouped) {
                actions.loadMoreGroupedLogs()
            } else {
                actions.loadMoreUngroupedLogs()
            }
        },
        setFilters: async (_, breakpoint) => {
            await breakpoint(500)
            actions.loadLogs()
        },
        setIsGrouped: async (_) => {
            actions.clearLogs()
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
