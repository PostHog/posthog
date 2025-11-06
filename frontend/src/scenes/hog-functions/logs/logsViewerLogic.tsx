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
export const LOG_VIEWER_LIMIT = 100

export type LogsViewerLogicProps = {
    logicKey?: string
    sourceType: 'hog_function' | 'hog_flow' | 'batch_exports' | 'external_data_jobs'
    sourceId: string
    groupByInstanceId?: boolean
    searchGroups?: string[]
    defaultFilters?: Partial<LogEntryParams>
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

export type LogEntryParams = {
    sourceType: 'hog_function' | 'hog_flow'
    sourceId: string
    levels: LogEntryLevel[]
    searchGroups: string[]
    dateFrom?: string
    dateTo?: string
    order: 'ASC' | 'DESC'
    instanceId?: string
}

const toKey = (log: LogEntry): string => {
    return `${log.instanceId}-${log.level}-${log.timestamp.toISOString()}`
}

const toAbsoluteClickhouseTimestamp = (timestamp: Dayjs): string => {
    // TRICKY: CH query is timezone aware so we dont send iso
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

const buildSearchFilters = ({ searchGroups, levels, instanceId }: LogEntryParams): string => {
    let query = hogql`\nAND lower(level) IN (${hogql.raw(levels.map((level) => `'${level.toLowerCase()}'`).join(','))})`

    searchGroups.forEach((search) => {
        query = (query + hogql`\nAND message ILIKE '%${hogql.raw(search)}%'`) as HogQLQueryString
    })

    if (instanceId) {
        query = (query + hogql`\nAND instance_id = ${instanceId}`) as HogQLQueryString
    }

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
            date_from: request.dateFrom ?? '-7d',
            date_to: request.dateTo,
        },
    })

    return response.results.map(
        (result): LogEntry => ({
            instanceId: result[0],
            timestamp: dayjs(result[1]),
            level: result[2].toUpperCase(),
            message: result[3],
        })
    )
}

const loadGroupedLogs = async (request: LogEntryParams): Promise<LogEntry[]> => {
    const query = hogql`
        SELECT instance_id, timestamp, level, message
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
        ORDER BY timestamp DESC`

    const response = await api.queryHogQL(query, {
        refresh: 'force_blocking',
        filtersOverride: {
            date_from: request.dateFrom ?? '-7d',
            date_to: request.dateTo,
        },
    })

    return response.results.map(
        (result): LogEntry => ({
            instanceId: result[0],
            timestamp: dayjs(result[1]),
            level: result[2].toUpperCase(),
            message: result[3],
        })
    )
}

const groupLogs = (logs: LogEntry[]): GroupedLogEntry[] => {
    const byId: Record<string, GroupedLogEntry> = {}
    const dedupeCache = new Set<string>()

    for (const log of logs) {
        const key = toKey(log)
        if (dedupeCache.has(key)) {
            continue
        }
        dedupeCache.add(key)
        const group = byId[log.instanceId] ?? {
            instanceId: log.instanceId,
            maxTimestamp: log.timestamp,
            minTimestamp: log.timestamp,
            logLevel: log.level,
            entries: [],
        }
        byId[log.instanceId] = group
        group.entries.push(log)
        group.maxTimestamp = log.timestamp.isAfter(group.maxTimestamp) ? log.timestamp : group.maxTimestamp
        group.minTimestamp = log.timestamp.isBefore(group.minTimestamp) ? log.timestamp : group.minTimestamp
        if (ALL_LOG_LEVELS.indexOf(log.level) > ALL_LOG_LEVELS.indexOf(group.logLevel)) {
            group.logLevel = log.level
        }
    }

    return Object.values(byId).map((group) => ({
        ...group,
        entries: group.entries.sort((a, b) => a.timestamp.diff(b.timestamp)),
    }))
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
                levels: props.defaultFilters?.levels ?? DEFAULT_LOG_LEVELS,
                date_from: props.defaultFilters?.dateFrom ?? '-7d',
                date_to: props.defaultFilters?.dateTo,
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
                        dateTo: toAbsoluteClickhouseTimestamp(values.oldestLogTimestamp),
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

                    return groupLogs(results)
                },
                loadMoreGroupedLogs: async () => {
                    if (!values.oldestLogTimestamp) {
                        return values.groupedLogs
                    }
                    const logParams: LogEntryParams = {
                        ...values.logEntryParams,
                        dateTo: toAbsoluteClickhouseTimestamp(values.oldestLogTimestamp),
                    }

                    const results = await loadGroupedLogs(logParams)

                    if (!results.length) {
                        actions.markLogsEnd()
                    }
                    return groupLogs([...results, ...values.groupedLogs.flatMap((group) => group.entries)])
                },

                addLogGroups: ({ logGroups }) => {
                    return groupLogs([
                        ...logGroups.flatMap((group) => group.entries),
                        ...values.groupedLogs.flatMap((group) => group.entries),
                    ])
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
                        dateFrom: toAbsoluteClickhouseTimestamp(values.newestLogTimestamp),
                        order: 'ASC',
                    }

                    let newLogs: LogEntry[] = []

                    if (values.isGrouped) {
                        const results = await loadGroupedLogs(logParams)

                        await breakpoint(10)

                        const newLogs: LogEntry[] = []
                        const newLogsToImmediateAdd: LogEntry[] = []
                        const existingLogIds = values.groupedLogs.map((log) => log.instanceId)

                        if (values.logsLoading) {
                            // TRICKY: Something changed whilst we were doing this query - we don't want to mess with things
                            // so we just exit
                            return values.hiddenLogs
                        }

                        for (const log of results) {
                            if (existingLogIds.includes(log.instanceId)) {
                                // If we already have this log group showing then we can just update it
                                newLogsToImmediateAdd.push(log)
                            } else {
                                // Otherwise we add it to the list of hidden logs
                                newLogs.push(log)
                            }
                        }

                        if (newLogsToImmediateAdd.length) {
                            // Update the existing logs with the new data
                            actions.loadGroupedLogsSuccess(
                                groupLogs([
                                    ...newLogsToImmediateAdd,
                                    ...values.groupedLogs.flatMap((group) => group.entries),
                                ])
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
            (s) => [(_, p) => p, s.filters],
            (props, filters): LogEntryParams => {
                const searchGroups = [filters.search, ...(props.searchGroups || [])].filter((x) => !!x) as string[]
                return {
                    ...props.defaultFilters,
                    levels: filters.levels,
                    searchGroups: searchGroups,
                    sourceType: props.sourceType,
                    sourceId: props.sourceId,
                    dateFrom: filters.date_from,
                    dateTo: filters.date_to,
                    order: 'DESC',
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
            cache.disposables.add(() => {
                const timeoutId = setTimeout(() => actions.loadNewerLogs(), POLLING_INTERVAL)
                return () => clearTimeout(timeoutId)
            }, 'pollingTimeout')
        },

        revealHiddenLogs: () => {
            if (!values.hiddenLogs.length) {
                return
            }

            if (values.isGrouped) {
                actions.loadMoreGroupedLogsSuccess(
                    groupLogs([...values.hiddenLogs, ...values.groupedLogs.flatMap((group) => group.entries)])
                )
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
    beforeUnmount(() => {
        // Disposables handle cleanup automatically
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
