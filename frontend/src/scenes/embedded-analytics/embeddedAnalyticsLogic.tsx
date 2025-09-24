import { actions, kea, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import {
    dateStringToDayJs,
    getDefaultInterval,
    isValidRelativeOrAbsoluteDate,
    updateDatesWithInterval,
} from 'lib/utils'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { urls } from 'scenes/urls'

import { NodeKind } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
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
    createFailedQueriesColumns,
    createFailedQueriesQuery,
    createLast20QueriesColumns,
    createLast20QueriesQuery,
} from './queries'

export interface EmbeddedAnalyticsLogicProps {
    tabId?: string
}

export const embeddedAnalyticsLogic = kea<embeddedAnalyticsLogicType>([
    path(['scenes', 'embedded-analytics', 'embeddedAnalyticsLogic']),
    tabAwareScene(),
    props({} as EmbeddedAnalyticsLogicProps),

    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setInterval: (interval: IntervalType) => ({ interval }),
        setDatesAndInterval: (dateFrom: string | null, dateTo: string | null, interval?: IntervalType) => ({
            dateFrom,
            dateTo,
            interval,
        }),
        setRequestNameBreakdownEnabled: (enabled: boolean) => ({ enabled }),
        setRequestNameFilter: (requestNames: string[]) => ({ requestNames }),
        ensureAllRequestNamesLoaded: true,
        loadRequestNames: true,
        setSearch: (search: string) => ({ search }),
        setActiveTab: (tab: EmbeddedTab) => ({ tab }),
    }),

    loaders(({}) => ({
        requestNames: [
            [] as string[],
            {
                loadRequestNames: async () => {
                    const query = hogql`
                        SELECT DISTINCT name
                        FROM query_log
                        WHERE is_personal_api_key_request
                            AND name IS NOT NULL
                            AND name != ''
                        ORDER BY name ASC
                    `

                    const response = await api.queryHogQL(query, {
                        refresh: 'force_blocking',
                    })

                    return response.results?.map((row: string[]) => row[0]) || []
                },
            },
        ],
    })),
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
        requestNameFilter: [
            [] as string[],
            {
                setRequestNameFilter: (_, { requestNames }) => requestNames,
            },
        ],
        search: ['', { setSearch: (_, { search }) => search }],
        activeTab: [
            EmbeddedTab.QUERY_ENDPOINTS as EmbeddedTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
    }),

    selectors({
        tiles: [
            (s) => [s.dateFilter, s.requestNameBreakdownEnabled, s.requestNameFilter, s.activeTab],
            (dateFilter, requestNameBreakdownEnabled, requestNameFilter, activeTab): EmbeddedQueryTile[] => {
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
                    requestNameFilter,
                }

                const expensiveQueriesColumns = createExpensiveQueriesColumns(requestNameBreakdownEnabled)
                const last20QueriesColumns = createLast20QueriesColumns(requestNameBreakdownEnabled)
                const failedQueriesColumns = createFailedQueriesColumns()

                const apiQueriesCountQuery = createApiQueriesCountQuery(queryConfig)
                const apiReadTbQuery = createApiReadTbQuery(queryConfig)
                const apiCpuSecondsQuery = createApiCpuSecondsQuery(queryConfig)
                const apiQueriesPerKeyQuery = createApiQueriesPerKeyQuery(queryConfig)
                const last20QueriesQuery = createLast20QueriesQuery(queryConfig)
                const expensiveQueriesQuery = createExpensiveQueriesQuery(queryConfig)
                const failedQueriesQuery = createFailedQueriesQuery(queryConfig)

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
                    {
                        kind: 'query',
                        tileId: EmbeddedAnalyticsTileId.API_FAILED_QUERIES,
                        title: 'Recently failed API request queries',
                        layout: {
                            colSpanClassName: 'md:col-span-full',
                        },
                        query: {
                            kind: NodeKind.DataVisualizationNode,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query: failedQueriesQuery,
                            },
                            display: ChartDisplayType.ActionsTable,
                            tableSettings: {
                                columns: failedQueriesColumns,
                                conditionalFormatting: [],
                            },
                        },
                        insightProps: {
                            dashboardItemId: 'embedded_analytics_failed_queries',
                            cachedInsight: null,
                        } as InsightLogicProps,
                        canOpenInsight: false,
                        canOpenModal: false,
                    },
                ]
            },
        ],
    }),

    tabAwareActionToUrl(({ values }) => {
        const actionToUrl = ({
            dateFilter = values.dateFilter,
            requestNameBreakdownEnabled = values.requestNameBreakdownEnabled,
            requestNameFilter = values.requestNameFilter,
        }): [string, Record<string, any> | undefined, string | undefined] | undefined => {
            const { dateFrom, dateTo, interval } = dateFilter
            const searchParams = { ...router.values.searchParams }

            if (values.activeTab === EmbeddedTab.USAGE) {
                if (dateFrom !== INITIAL_DATE_FROM) {
                    searchParams.dateFrom = dateFrom
                } else {
                    delete searchParams.dateFrom
                }

                if (dateTo !== INITIAL_DATE_TO) {
                    searchParams.dateTo = dateTo
                } else {
                    delete searchParams.dateTo
                }

                if (interval !== INITIAL_INTERVAL) {
                    searchParams.interval = interval
                } else {
                    delete searchParams.interval
                }

                if (requestNameBreakdownEnabled !== INITIAL_REQUEST_NAME_BREAKDOWN_ENABLED) {
                    searchParams.requestNameBreakdownEnabled = requestNameBreakdownEnabled
                } else {
                    delete searchParams.requestNameBreakdownEnabled
                }

                if (requestNameFilter.length > 0) {
                    searchParams.requestNameFilter = requestNameFilter.join(',')
                } else {
                    delete searchParams.requestNameFilter
                }
            } else {
                delete searchParams.dateFrom
                delete searchParams.dateTo
                delete searchParams.interval
                delete searchParams.requestNameBreakdownEnabled
                delete searchParams.requestNameFilter
            }

            return [router.values.location.pathname, searchParams, router.values.location.hash]
        }

        return {
            setActiveTab: actionToUrl,
            setDates: actionToUrl,
            setDatesAndInterval: actionToUrl,
            setRequestNameBreakdownEnabled: actionToUrl,
            setRequestNameFilter: actionToUrl,
        }
    }),

    tabAwareUrlToAction(({ actions }) => ({
        [urls.embeddedAnalytics(':tab')]: (path, searchParams) => {
            actions.setActiveTab(path.tab as EmbeddedTab)
            if (path.tab === EmbeddedTab.USAGE) {
                const { dateFrom, dateTo, interval, requestNameBreakdownEnabled, requestNameFilter } = searchParams
                actions.setDatesAndInterval(
                    dateFrom ?? INITIAL_DATE_FROM,
                    dateTo ?? INITIAL_DATE_TO,
                    interval ?? INITIAL_INTERVAL
                )
                actions.setRequestNameBreakdownEnabled(
                    requestNameBreakdownEnabled ?? INITIAL_REQUEST_NAME_BREAKDOWN_ENABLED
                )
                actions.setRequestNameFilter(requestNameFilter ? requestNameFilter.split(',') : [])
            }
        },
    })),

    permanentlyMount(),
])
