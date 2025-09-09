import { kea, path, selectors } from 'kea'

import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType, InsightLogicProps } from '~/types'

import { EmbeddedAnalyticsTileId, EmbeddedQueryTile } from './common'
import type { embeddedAnalyticsLogicType } from './embeddedAnalyticsLogicType'

export const embeddedAnalyticsLogic = kea<embeddedAnalyticsLogicType>([
    path(['scenes', 'embedded-analytics', 'embeddedAnalyticsLogic']),

    selectors({
        tiles: [
            () => [],
            (): EmbeddedQueryTile[] => [
                {
                    kind: 'query',
                    tileId: EmbeddedAnalyticsTileId.API_QUERIES_COUNT,
                    title: 'Number of queries per day',
                    layout: {
                        colSpanClassName: 'md:col-span-2',
                    },
                    query: {
                        kind: NodeKind.DataVisualizationNode,
                        source: {
                            kind: NodeKind.HogQLQuery,
                            query: `select event_date, count(1) as number_of_queries
                                    from query_log
                                    where is_personal_api_key_request and event_date >= today() - interval 21 day
                                    group by event_date
                                    order by event_date asc`,
                        },
                        display: ChartDisplayType.ActionsLineGraph,
                        chartSettings: {
                            xAxis: { column: 'event_date' },
                            yAxis: [
                                {
                                    column: 'number_of_queries',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                }
                            ],
                            showLegend: true,
                            seriesBreakdownColumn: null,
                        }
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
                    title: 'Read TB per day',
                    layout: {
                        colSpanClassName: 'md:col-span-2',
                    },
                    query: {
                        kind: NodeKind.DataVisualizationNode,
                        source: {
                            kind: NodeKind.HogQLQuery,
                            query: `select 
                                        event_date, 
                                        sum(read_bytes)/1e12 as read_tb
                                    from query_log
                                    where 
                                        is_personal_api_key_request 
                                        and event_date >= today() - interval 21 day
                                    group by event_date
                                    order by event_date asc`,
                        },
                        display: ChartDisplayType.ActionsLineGraph,
                        chartSettings: {
                            xAxis: { column: 'event_date' },
                            yAxis: [
                                {
                                    column: 'read_tb',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                }
                            ],
                            showLegend: true,
                            seriesBreakdownColumn: null,
                        }
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
                    title: 'Used CPU seconds per day',
                    layout: {
                        colSpanClassName: 'md:col-span-2',
                        // rowSpanClassName: 'md:row-span-2'
                    },
                    query: {
                        kind: NodeKind.DataVisualizationNode,
                        source: {
                            kind: NodeKind.HogQLQuery,
                            query: `select 
                                        event_date, 
                                        sum(cpu_microseconds)/1e6 as cpu_sec
                                    from query_log
                                    where 
                                        is_personal_api_key_request 
                                        and event_date >= today() - interval 21 day
                                    group by event_date
                                    order by event_date asc`,
                        },
                        display: ChartDisplayType.ActionsLineGraph,
                        chartSettings: {
                            xAxis: { column: 'event_date' },
                            yAxis: [
                                {
                                    column: 'cpu_sec',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                }
                            ],
                            showLegend: true,
                            seriesBreakdownColumn: null,
                        }
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
                    title: 'Number of queries per personal api key',
                    layout: {
                        colSpanClassName: 'md:col-span-2',
                    },
                    query: {
                        kind: NodeKind.DataVisualizationNode,
                        source: {
                            kind: NodeKind.HogQLQuery,
                            query: `select event_date, api_key_label, count(1) as total_queries
                                    from query_log 
                                    where event_date > today() - interval 28 day
                                        and is_personal_api_key_request
                                    group by event_date, api_key_label
                                    order by event_date`,
                        },
                        display: ChartDisplayType.ActionsLineGraph,
                        chartSettings: {
                            xAxis: { column: 'event_date' },
                            yAxis: [
                                {
                                    column: 'total_queries',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                }
                            ],
                            showLegend: true,
                            seriesBreakdownColumn: 'api_key_label',
                        }
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
                    title: 'Last 20 queries',
                    layout: {
                        colSpanClassName: 'md:col-span-full',
                    },
                    query: {
                        kind: NodeKind.DataVisualizationNode,
                        source: {
                            kind: NodeKind.HogQLQuery,
                            query: `select event_time as finished_at, query_duration_ms, query, created_by 
                                    from query_log
                                    where is_personal_api_key_request
                                        and event_date = today()
                                    order by event_time desc
                                    limit 20`,
                        },
                        display: ChartDisplayType.ActionsTable,
                        chartSettings: {
                            xAxis: { column: 'query_start_time' },
                            yAxis: [
                                {
                                    column: 'query_duration_ms',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                },
                                {
                                    column: 'created_by',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                }
                            ],
                            seriesBreakdownColumn: null
                        },
                        tableSettings: {
                            columns: [
                                {
                                    column: 'finished_at',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                },
                                {
                                    column: 'query_duration_ms',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                },
                                {
                                    column: 'query',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                },
                                {
                                    column: 'created_by',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                }
                            ],
                            conditionalFormatting: []
                        }
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
                    title: '25 most expensive queries',
                    layout: {
                        colSpanClassName: 'md:col-span-full',
                    },
                    query: {
                        kind: NodeKind.DataVisualizationNode,
                        source: {
                            kind: NodeKind.HogQLQuery,
                            query: `select 
                                        query_start_time, 
                                        query,
                                        query_duration_ms,
                                        read_bytes / 1e12 as read_tb, 
                                        cpu_microseconds / 1e6 as cpu_sec,
                                        created_by
                                    from query_log
                                    where 
                                        is_personal_api_key_request
                                        and event_date = today()
                                    order by read_tb desc
                                    limit 25`,
                        },
                        display: ChartDisplayType.ActionsTable,
                        chartSettings: {
                            xAxis: { column: 'query_start_time' },
                            yAxis: [
                                {
                                    column: 'read_tb',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                },
                                {
                                    column: 'cpu_sec',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                }
                            ],
                            seriesBreakdownColumn: null
                        },
                        tableSettings: {
                            columns: [
                                {
                                    column: 'query_start_time',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                },
                                {
                                    column: 'query',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                },
                                {
                                    column: 'query_duration_ms',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                },
                                {
                                    column: 'read_tb',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                },
                                {
                                    column: 'cpu_sec',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                },
                                {
                                    column: 'created_by',
                                    settings: { formatting: { prefix: '', suffix: '' } }
                                }
                            ],
                            conditionalFormatting: []
                        }
                    },
                    insightProps: {
                        dashboardItemId: 'embedded_analytics_expensive_queries',
                        cachedInsight: null,
                    } as InsightLogicProps,
                    canOpenInsight: false,
                    canOpenModal: false,
                },
            ],
        ],
    }),
])
