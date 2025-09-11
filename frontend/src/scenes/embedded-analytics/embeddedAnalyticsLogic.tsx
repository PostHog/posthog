import { actions, events, kea, key, path, props, reducers, selectors } from 'kea'

import { dayjs } from 'lib/dayjs'
import {
    dateStringToDayJs,
    getDefaultInterval,
    isValidRelativeOrAbsoluteDate,
    updateDatesWithInterval,
} from 'lib/utils'

import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType, InsightLogicProps, IntervalType } from '~/types'

import { EmbeddedAnalyticsTileId, EmbeddedQueryTile } from './common'
import type { embeddedAnalyticsLogicType } from './embeddedAnalyticsLogicType'
import {
    createApiCpuSecondsQuery,
    createApiQueriesCountQuery,
    createApiQueriesPerKeyQuery,
    createApiReadTbQuery,
    createExpensiveQueriesColumns,
    createExpensiveQueriesQuery,
    createLast20QueriesColumns,
    createLast20QueriesQuery,
} from './queries'

const INITIAL_DATE_FROM = '-7d' as string
const INITIAL_DATE_TO = null as string | null
const INITIAL_INTERVAL = getDefaultInterval(INITIAL_DATE_FROM, INITIAL_DATE_TO)

export const EMBEDDED_ANALYTICS_DATA_COLLECTION_NODE_ID = 'EmbeddedAnalyticsScene'

export interface EmbeddedAnalyticsLogicProps {
    dashboardId?: string | number
}

export const embeddedAnalyticsLogic = kea<embeddedAnalyticsLogicType>([
    path(['scenes', 'embedded-analytics', 'embeddedAnalyticsLogic']),
    props({} as EmbeddedAnalyticsLogicProps),
    key(({ dashboardId }) => dashboardId || 'default'),

    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setInterval: (interval: IntervalType) => ({ interval }),
        setDatesAndInterval: (dateFrom: string | null, dateTo: string | null, interval?: IntervalType) => ({
            dateFrom,
            dateTo,
            interval,
        }),
        setRequestNameBreakdownEnabled: (enabled: boolean) => ({ enabled }),
    }),

    reducers({
        dateFilter: [
            {
                dateFrom: INITIAL_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
                interval: INITIAL_INTERVAL,
            } as { dateFrom: string | null; dateTo: string | null; interval: IntervalType },
            {
                setDates: (_, { dateTo, dateFrom }) => {
                    if (dateTo && !isValidRelativeOrAbsoluteDate(dateTo)) {
                        dateTo = INITIAL_DATE_TO
                    }
                    if (dateFrom && !isValidRelativeOrAbsoluteDate(dateFrom)) {
                        dateFrom = INITIAL_DATE_FROM
                    }
                    return {
                        dateTo,
                        dateFrom: dateFrom || INITIAL_DATE_FROM,
                        interval: getDefaultInterval(dateFrom, dateTo),
                    }
                },
                setInterval: ({ dateFrom: oldDateFrom, dateTo: oldDateTo }, { interval }) => {
                    const { dateFrom, dateTo } = updateDatesWithInterval(interval, oldDateFrom, oldDateTo)
                    return {
                        dateTo,
                        dateFrom: dateFrom || INITIAL_DATE_FROM,
                        interval,
                    }
                },
                setDatesAndInterval: (_, { dateTo, dateFrom, interval }) => {
                    if (!dateFrom && !dateTo) {
                        dateFrom = INITIAL_DATE_FROM
                        dateTo = INITIAL_DATE_TO
                    }
                    if (dateTo && !isValidRelativeOrAbsoluteDate(dateTo)) {
                        dateTo = INITIAL_DATE_TO
                    }
                    if (dateFrom && !isValidRelativeOrAbsoluteDate(dateFrom)) {
                        dateFrom = INITIAL_DATE_FROM
                    }
                    return {
                        dateTo,
                        dateFrom: dateFrom || INITIAL_DATE_FROM,
                        interval: interval || getDefaultInterval(dateFrom, dateTo),
                    }
                },
            },
        ],
        requestNameBreakdownEnabled: [
            false,
            {
                setRequestNameBreakdownEnabled: (_, { enabled }) => enabled,
            },
        ],
    }),

    selectors({
        tiles: [
            (s) => [s.dateFilter, s.requestNameBreakdownEnabled],
            (dateFilter, requestNameBreakdownEnabled): EmbeddedQueryTile[] => {
                const dateFromDayjs = dateStringToDayJs(dateFilter.dateFrom)
                const dateToDayjs = dateFilter.dateTo ? dateStringToDayJs(dateFilter.dateTo) : null

                const dateFrom = dateFromDayjs
                    ? dateFromDayjs.format('YYYY-MM-DD')
                    : dayjs().subtract(7, 'day').format('YYYY-MM-DD')

                const dateTo = dateToDayjs ? dateToDayjs.format('YYYY-MM-DD') : dayjs().format('YYYY-MM-DD')

                const queryConfig = {
                    dateFrom,
                    dateTo,
                    requestNameBreakdownEnabled,
                }

                const expensiveQueriesColumns = createExpensiveQueriesColumns(requestNameBreakdownEnabled)
                const last20QueriesColumns = createLast20QueriesColumns(requestNameBreakdownEnabled)
                const apiQueriesCountQuery = createApiQueriesCountQuery(queryConfig)
                const apiReadTbQuery = createApiReadTbQuery(queryConfig)
                const apiCpuSecondsQuery = createApiCpuSecondsQuery(queryConfig)
                const apiQueriesPerKeyQuery = createApiQueriesPerKeyQuery(queryConfig)
                const last20QueriesQuery = createLast20QueriesQuery(queryConfig)
                const expensiveQueriesQuery = createExpensiveQueriesQuery(queryConfig)

                return [
                    {
                        kind: 'query',
                        tileId: EmbeddedAnalyticsTileId.API_QUERIES_COUNT,
                        title: 'Number of API requests per day',
                        layout: {
                            colSpanClassName: 'md:col-span-2',
                        },
                        query: {
                            kind: NodeKind.DataVisualizationNode,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query: apiQueriesCountQuery,
                            },
                            display: ChartDisplayType.ActionsBar,
                            chartSettings: {
                                xAxis: { column: 'event_date' },
                                yAxis: [
                                    {
                                        column: 'number_of_queries',
                                        settings: { formatting: { prefix: '', suffix: '' } },
                                    },
                                ],
                                showLegend: requestNameBreakdownEnabled ? true : false,
                                seriesBreakdownColumn: requestNameBreakdownEnabled ? 'name' : null,
                            },
                        },
                        insightProps: {
                            dashboardItemId: 'embedded_analytics_api_queries',
                            cachedInsight: null,
                        } as InsightLogicProps,
                        canOpenInsight: false,
                        canOpenModal: false,
                    },
                    {
                        kind: 'query',
                        tileId: EmbeddedAnalyticsTileId.API_READ_TB,
                        title: 'TB read by API requests per day',
                        layout: {
                            colSpanClassName: 'md:col-span-2',
                        },
                        query: {
                            kind: NodeKind.DataVisualizationNode,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query: apiReadTbQuery,
                            },
                            display: ChartDisplayType.ActionsBar,
                            chartSettings: {
                                xAxis: { column: 'event_date' },
                                yAxis: [
                                    {
                                        column: 'read_tb',
                                        settings: { formatting: { prefix: '', suffix: '' } },
                                    },
                                ],
                                showLegend: requestNameBreakdownEnabled ? true : false,
                                seriesBreakdownColumn: requestNameBreakdownEnabled ? 'name' : null,
                            },
                        },
                        insightProps: {
                            dashboardItemId: 'embedded_analytics_read_tb',
                            cachedInsight: null,
                        } as InsightLogicProps,
                        canOpenInsight: false,
                        canOpenModal: false,
                    },
                    {
                        kind: 'query',
                        tileId: EmbeddedAnalyticsTileId.API_CPU_SECONDS,
                        title: 'CPU seconds used by API requests per day',
                        layout: {
                            colSpanClassName: 'md:col-span-2',
                        },
                        query: {
                            kind: NodeKind.DataVisualizationNode,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query: apiCpuSecondsQuery,
                            },
                            display: ChartDisplayType.ActionsLineGraph,
                            chartSettings: {
                                xAxis: { column: 'event_date' },
                                yAxis: [
                                    {
                                        column: 'cpu_sec',
                                        settings: { formatting: { prefix: '', suffix: '' } },
                                    },
                                ],
                                showLegend: requestNameBreakdownEnabled ? true : false,
                                seriesBreakdownColumn: requestNameBreakdownEnabled ? 'name' : null,
                            },
                        },
                        insightProps: {
                            dashboardItemId: 'embedded_analytics_cpu_sec',
                            cachedInsight: null,
                        } as InsightLogicProps,
                        canOpenInsight: false,
                        canOpenModal: false,
                    },
                    {
                        kind: 'query',
                        tileId: EmbeddedAnalyticsTileId.API_QUERIES_PER_KEY,
                        title: 'Number of API requests by personal api key per day',
                        layout: {
                            colSpanClassName: 'md:col-span-2',
                        },
                        query: {
                            kind: NodeKind.DataVisualizationNode,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query: apiQueriesPerKeyQuery,
                            },
                            display: ChartDisplayType.ActionsLineGraph,
                            chartSettings: {
                                xAxis: { column: 'event_date' },
                                yAxis: [
                                    {
                                        column: 'total_queries',
                                        settings: { formatting: { prefix: '', suffix: '' } },
                                    },
                                ],
                                showLegend: true,
                                seriesBreakdownColumn: 'api_key_label',
                            },
                        },
                        insightProps: {
                            dashboardItemId: 'embedded_analytics_queries_per_key',
                            cachedInsight: null,
                        } as InsightLogicProps,
                        canOpenInsight: false,
                        canOpenModal: false,
                    },
                    {
                        kind: 'query',
                        tileId: EmbeddedAnalyticsTileId.API_LAST_20_QUERIES,
                        title: 'Last 20 API requests',
                        layout: {
                            colSpanClassName: 'md:col-span-full',
                        },
                        query: {
                            kind: NodeKind.DataVisualizationNode,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query: last20QueriesQuery,
                            },
                            display: ChartDisplayType.ActionsTable,
                            chartSettings: {
                                xAxis: { column: 'query_start_time' },
                                yAxis: [
                                    {
                                        column: 'query_duration_ms',
                                        settings: { formatting: { prefix: '', suffix: '' } },
                                    },
                                    {
                                        column: 'created_by',
                                        settings: { formatting: { prefix: '', suffix: '' } },
                                    },
                                ],
                                seriesBreakdownColumn: null,
                            },
                            tableSettings: {
                                columns: last20QueriesColumns,
                                conditionalFormatting: [],
                            },
                        },
                        insightProps: {
                            dashboardItemId: 'embedded_analytics_last_20_queries',
                            cachedInsight: null,
                        } as InsightLogicProps,
                        canOpenInsight: false,
                        canOpenModal: false,
                    },
                    {
                        kind: 'query',
                        tileId: EmbeddedAnalyticsTileId.API_EXPENSIVE_QUERIES,
                        title: '25 most expensive API request queries',
                        layout: {
                            colSpanClassName: 'md:col-span-full',
                        },
                        query: {
                            kind: NodeKind.DataVisualizationNode,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query: expensiveQueriesQuery,
                            },
                            display: ChartDisplayType.ActionsTable,
                            chartSettings: {
                                xAxis: { column: 'query_start_time' },
                                yAxis: [
                                    {
                                        column: 'read_tb',
                                        settings: { formatting: { prefix: '', suffix: '' } },
                                    },
                                    {
                                        column: 'cpu_sec',
                                        settings: { formatting: { prefix: '', suffix: '' } },
                                    },
                                ],
                                seriesBreakdownColumn: null,
                            },
                            tableSettings: {
                                columns: expensiveQueriesColumns,
                                conditionalFormatting: [],
                            },
                        },
                        insightProps: {
                            dashboardItemId: 'embedded_analytics_expensive_queries',
                            cachedInsight: null,
                        } as InsightLogicProps,
                        canOpenInsight: false,
                        canOpenModal: false,
                    },
                ]
            },
        ],
    }),

    events(({ actions, values }) => ({
        afterMount: () => {
            // Force initial breakdown state setup
            actions.setRequestNameBreakdownEnabled(values.requestNameBreakdownEnabled)
        },
    })),
])
