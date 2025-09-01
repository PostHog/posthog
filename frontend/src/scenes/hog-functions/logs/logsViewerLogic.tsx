import {
    actions,
    afterMount,
    beforeUnmount,
    kea,
    key,
    listeners,
    path,
    props,
    propsChanged,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { teamLogic } from 'scenes/teamLogic'

import { HogQLQueryString, hogql } from '~/queries/utils'
import { LogEntryLevel } from '~/types'

import type { logsViewerLogicType } from './logsViewerLogicType'

export const ALL_LOG_LEVELS: LogEntryLevel[] = ['DEBUG', 'LOG', 'INFO', 'WARNING', 'ERROR']
export const DEFAULT_LOG_LEVELS: LogEntryLevel[] = ['DEBUG', 'LOG', 'INFO', 'WARNING', 'ERROR']
export const POLLING_INTERVAL = 5000
export const LOG_VIEWER_LIMIT = 10

export type LogsViewerLogicProps = {
    logicKey?: string
    sourceType: 'hog_function' | 'hog_flow'
    sourceId: string
    groupByInstanceId?: boolean
    searchGroups?: string[]
}

export type LogsViewerFilters = {
    levels: LogEntryLevel[]
    search: string
    date_from?: string
    date_to?: string
}

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

const toKey = (log: LogEntry): string => {
    return `${log.instanceId}-${log.level}-${log.timestamp.toISOString()}`
}

const toAbsoluteClickhouseTimestamp = (timestamp: Dayjs): string => {
    // We need to include milliseconds for accuracy
    return timestamp.format('YYYY-MM-DD HH:mm:ss.SSS')
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
        clearHiddenLogs: true,
        markLogsEnd: true,
        revealHiddenLogs: true,
        setRowExpanded: (instanceId: string, expanded: boolean) => ({ instanceId, expanded }),
        scheduleLoadNewerLogs: true,
        loadLogs: true,
        loadNewerLogs: true,
        loadOlderLogs: true,
        clearLogs: true,
        loadGroupedLogs: true,
        loadUngroupedLogs: true,
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
                loadUngroupedLogs: async (_, breakpoint) => {
                    await breakpoint(10)
                    actions.clearHiddenLogs()
                    const results = await loadLogs(values.logEntryParams)
                    await breakpoint(10)
                    return results
                },
                loadMoreUngroupedLogs: async () => {
                    if (!values.oldestLogTimestamp) {
                        return values.unGroupedLogs
                    }
                    const logParams: LogEntryParams = {
                        ...values.logEntryParams,
                        date_to: toAbsoluteClickhouseTimestamp(values.oldestLogTimestamp),
                    }

                    const results = await loadLogs(logParams)

                    if (!results.length) {
                        actions.markLogsEnd()
                    }

                    const newLogs = results.filter((log) => !values.allLogEntryKeys.has(toKey(log)))
                    return [...newLogs, ...values.unGroupedLogs].sort((a, b) => b.timestamp.diff(a.timestamp))
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
                        date_to: toAbsoluteClickhouseTimestamp(values.oldestLogTimestamp),
                    }

                    const results = await loadGroupedLogs(logParams)

                    if (!results.length) {
                        actions.markLogsEnd()
                    }
                    return sanitizeGroupedLogs([...results, ...values.groupedLogs])
                },

                addLogGroups: ({ logGroups }) => {
                    return sanitizeGroupedLogs([...logGroups, ...values.groupedLogs])
                },
            },
        ],

        hiddenLogs: [
            [] as LogEntry[],
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
                        date_from: toAbsoluteClickhouseTimestamp(values.newestLogTimestamp),
                        order: 'ASC',
                    }

                    let newLogs: LogEntry[] = []

                    if (values.isGrouped) {
                        const results = await loadGroupedLogs(logParams)

                        await breakpoint(10)

                        const newLogs: LogEntry[] = []
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
                                newLogs.push(...log.entries)
                            }
                        }

                        if (existingLogsToUpdate.length) {
                            // Update the existing logs with the new data
                            actions.loadGroupedLogsSuccess(
                                sanitizeGroupedLogs([...existingLogsToUpdate, ...values.groupedLogs])
                            )
                        }
                    } else {
                        const results = await loadLogs(logParams)
                        await breakpoint(10)
                        newLogs = results
                    }

                    actions.scheduleLoadNewerLogs()

                    // Filter out any duplicates as the time ranges are never perfectly accurate
                    newLogs = newLogs.filter((log) => !values.allLogEntryKeys.has(toKey(log)))

                    return [...newLogs, ...values.hiddenLogs]
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

        allLogEntries: [
            (s) => [s.groupedLogs, s.unGroupedLogs, s.hiddenLogs],
            (groupedLogs, unGroupedLogs, hiddenLogs): LogEntry[] => {
                return [...groupedLogs.flatMap((log) => log.entries), ...unGroupedLogs, ...hiddenLogs]
            },
        ],

        allLogEntryKeys: [
            (s) => [s.allLogEntries],
            (allLogEntries): Set<string> => {
                return new Set(allLogEntries.map(toKey))
            },
        ],

        newestLogTimestamp: [
            (s) => [s.allLogEntries],
            (allLogEntries): Dayjs | null => {
                const item = allLogEntries.reduce(
                    (max, log) => {
                        if (!max) {
                            return log.timestamp
                        }
                        return log.timestamp.isAfter(max) ? log.timestamp : max
                    },
                    null as Dayjs | null
                )

                return item ? item.tz(teamLogic.findMounted()?.values.currentTeam?.timezone) : null
            },
        ],

        oldestLogTimestamp: [
            (s) => [s.allLogEntries],
            (allLogEntries): Dayjs | null => {
                return allLogEntries.reduce(
                    (min, log) => {
                        if (!min) {
                            return log.timestamp
                        }
                        return log.timestamp.isBefore(min) ? log.timestamp : min
                    },
                    null as Dayjs | null
                )
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
            clearTimeout(cache.pollingTimeout)

            if (values.isGrouped) {
                actions.loadGroupedLogs()
            } else {
                actions.loadUngroupedLogs()
            }
        },
        loadOlderLogs: () => {
            if (values.isGrouped) {
                actions.loadMoreGroupedLogs()
            } else {
                actions.loadMoreUngroupedLogs()
            }
        },
        setFilters: async ({ filters }, breakpoint) => {
            await breakpoint(filters.search ? 500 : 10) // Longer debounce when typing in the search field
            actions.loadLogs()
        },
        setIsGrouped: async () => {
            actions.clearLogs()
            actions.loadLogs()
        },
        loadGroupedLogsSuccess: () => actions.scheduleLoadNewerLogs(),
        loadUngroupedLogsSuccess: () => actions.scheduleLoadNewerLogs(),
        scheduleLoadNewerLogs: () => {
            clearTimeout(cache.pollingTimeout)
            cache.pollingTimeout = setTimeout(() => actions.loadNewerLogs(), POLLING_INTERVAL)
        },

        revealHiddenLogs: () => {
            if (!values.hiddenLogs.length) {
                return
            }

            // TODO: Add the logs to the right reducer
            if (values.isGrouped) {
            } else {
                actions.loadMoreUngroupedLogsSuccess(
                    [...values.unGroupedLogs, ...values.hiddenLogs].sort((a, b) => b.timestamp.diff(a.timestamp))
                )
            }

            actions.clearHiddenLogs()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadLogs()
    }),
    beforeUnmount(({ cache }) => {
        clearInterval(cache.pollingTimeout)
    }),
    actionToUrl(({ values }) => {
        const syncProperties = (
            properties: Record<string, any>
        ): [string, Record<string, any>, Record<string, any>] => {
            const newSearch = { ...router.values.searchParams, ...properties }
            Object.keys(properties).forEach((key) => {
                if (properties[key] === null || properties[key] === undefined) {
                    delete newSearch[key]
                }
            })
            return [router.values.location.pathname, newSearch, router.values.hashParams]
        }

        return {
            setFilters: ({ filters }) => syncProperties(filters),
            setIsGrouped: () => syncProperties({ grouped: values.isGrouped }),
        }
    }),
    urlToAction(({ actions, values }) => {
        const reactToTabChange = (_: any, search: Record<string, any>): void => {
            Object.keys(search).forEach((key) => {
                if (key in values.filters && search[key] !== values.filters[key as keyof LogsViewerFilters]) {
                    actions.setFilters({ [key]: search[key] })
                }
            })

            if (typeof search.grouped === 'boolean' && search.grouped !== values.isGrouped) {
                actions.setIsGrouped(search.grouped)
            }
        }

        return {
            '*': reactToTabChange,
        }
    }),
])
