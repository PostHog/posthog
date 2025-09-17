import { actions, kea, key, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { dayjs } from 'lib/dayjs'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import {
    dateStringToDayJs,
    getDefaultInterval,
    isValidRelativeOrAbsoluteDate,
    updateDatesWithInterval,
} from 'lib/utils'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType, InsightLogicProps, IntervalType } from '~/types'

import {
    EmbeddedAnalyticsTileId,
    EmbeddedQueryTile,
    EmbeddedTab,
    INITIAL_DATE_FROM,
    INITIAL_DATE_TO,
    INITIAL_INTERVAL,
    INITIAL_REQUEST_NAME_BREAKDOWN_ENABLED,
} from './common'
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
import { ActionToUrlPayload } from 'kea-router/lib/types'

export const EMBEDDED_ANALYTICS_DATA_COLLECTION_NODE_ID = 'embedded-analytics'

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
        setActiveTab: (tab: EmbeddedTab) => ({ tab }),
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
            INITIAL_REQUEST_NAME_BREAKDOWN_ENABLED as boolean,
            {
                setRequestNameBreakdownEnabled: (_, { enabled }) => enabled,
            },
        ],
        activeTab: [
            EmbeddedTab.QUERY_ENDPOINTS as EmbeddedTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
    }),

    selectors({
        tiles: [
            (s) => [s.dateFilter, s.requestNameBreakdownEnabled, s.activeTab],
            (dateFilter, requestNameBreakdownEnabled, activeTab): EmbeddedQueryTile[] => {
                if (activeTab === EmbeddedTab.QUERY_ENDPOINTS) {
                    return []
                }

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

    tabAwareActionToUrl(({ values }): ActionToUrlPayload<embeddedAnalyticsLogicType> => {
        const actionToUrl = ({
            dateFilter = values.dateFilter,
            requestNameBreakdownEnabled = values.requestNameBreakdownEnabled,
        }) => {
            if (router.values.searchParams['tab'] === EmbeddedTab.QUERY_ENDPOINTS) {
                return
            }
            const tab = values.activeTab === EmbeddedTab.QUERY_ENDPOINTS ? undefined : values.activeTab

            const { dateFrom, dateTo, interval } = dateFilter

            let filters: {
                dateFrom?: string | null
                dateTo?: string | null
                interval?: IntervalType
                requestNameBreakdownEnabled?: boolean
            } = {}
            if (tab === EmbeddedTab.USAGE) {
                if (dateFrom !== INITIAL_DATE_FROM) {
                    filters.dateFrom = dateFrom
                }
                if (dateTo !== INITIAL_DATE_TO) {
                    filters.dateTo = dateTo
                }
                if (interval !== INITIAL_INTERVAL) {
                    filters.interval = interval
                }
                if (requestNameBreakdownEnabled !== INITIAL_REQUEST_NAME_BREAKDOWN_ENABLED) {
                    filters.requestNameBreakdownEnabled = requestNameBreakdownEnabled
                }
            }

            return [
                router.values.location.pathname,
                { ...router.values.searchParams, tab, ...filters },
                router.values.location.hash,
            ]
        }

        return {
            setActiveTab: actionToUrl,
            setDates: actionToUrl,
            setDatesAndInterval: actionToUrl,
            setRequestNameBreakdownEnabled: actionToUrl,
        }
    }),

    tabAwareUrlToAction(({ actions }) => ({
        [urls.embeddedAnalytics()]: (_, searchParams) => {
            const tab = searchParams['tab'] || EmbeddedTab.QUERY_ENDPOINTS
            const { dateFrom, dateTo, interval, requestNameBreakdownEnabled } = searchParams

            actions.setActiveTab(tab)
            actions.setDatesAndInterval(dateFrom, dateTo, interval)
            actions.setRequestNameBreakdownEnabled(requestNameBreakdownEnabled)
        },
    })),
])
