import { actions, connect, kea, path, reducers, selectors } from 'kea'
import type { PaginatedResponse } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dataWarehouseSettingsLogic } from 'scenes/data-warehouse/settings/dataWarehouseSettingsLogic'

import { DateRange, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { QuerySchema } from '~/queries/schema/schema-general'
import { BreakdownAttributionType, ChartDisplayType, ExternalDataSource } from '~/types'

import type { revenueAnalyticsLogicType } from './revenueAnalyticsLogicType'

export const REVENUE_ANALYTICS_DATA_COLLECTION_NODE_ID = 'revenue-analytics-data-collection'

export enum ProductTab {
    OVERVIEW = 'overview',
    SUBSCRIPTIONS = 'subscriptions',
    CUSTOMERS = 'customers',
}

export enum TileId {
    REVENUE = 'revenue',
    SUBSCRIPTIONS = 'subscriptions',
    CUSTOMERS = 'customers',
    CHURN = 'churn',
    MRR = 'mrr',
    ARR = 'arr',
    LTV = 'ltv',
    PAYMENT_METHODS = 'payment_methods',
    ANNUAL_RUN_RATE = 'annual_run_rate',
    CUSTOMER_CHURN_RATE = 'customer_churn_rate',
    AVERAGE_REVENUE_PER_ACCOUNT = 'average_revenue_per_account',
    GROSS_MRR_CHURN_RATE = 'gross_mrr_churn_rate',
    NET_MRR_CHURN_RATE = 'net_mrr_churn_rate',
    AVERAGE_SALE_PRICE = 'average_sale_price',
    NET_CASH_FLOW = 'net_cash_flow',
}

export type TileVisualizationOption = 'table' | 'graph'

export interface TileLayout {
    colSpanClassName?: string
    rowSpanClassName?: string
    orderWhenLargeClassName?: string
    className?: string
}

export interface BaseTile {
    tileId: TileId
    layout: TileLayout
}

export interface QueryTile extends BaseTile {
    kind: 'query'
    title?: string
    query: QuerySchema
    insightProps?: Partial<InsightVizNode>
    control?: JSX.Element
    showIntervalSelect?: boolean
    canOpenModal?: boolean
    canOpenInsight?: boolean
    docs?: {
        url?: string
        title: string
        description: string | JSX.Element
    }
}

export interface TabsTile extends BaseTile {
    kind: 'tabs'
    activeTabId: string
    setTabId: (id: string) => void
    tabs: {
        id: string
        title: string
        linkText: string
        query: QuerySchema
        insightProps?: Partial<InsightVizNode>
        control?: JSX.Element
        showIntervalSelect?: boolean
        canOpenModal?: boolean
        canOpenInsight?: boolean
        docs?: {
            url?: string
            title: string
            description: string | JSX.Element
        }
    }[]
}

export interface CustomersTile extends BaseTile {
    kind: 'customers'
    title: string
}

export interface ChurnTile extends BaseTile {
    kind: 'churn'
    title: string
}

export type Tile = QueryTile | TabsTile | CustomersTile | ChurnTile

export const revenueAnalyticsLogic = kea<revenueAnalyticsLogicType>([
    path(['scenes', 'revenue-analytics', 'revenueAnalyticsLogic']),
    connect({
        values: [dataWarehouseSettingsLogic, ['dataWarehouseSources']],
    }),
    actions({
        setProductTab: (tab: ProductTab) => ({ tab }),
        setDateRange: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setTileVisualization: (tileId: TileId, visualization: TileVisualizationOption) => ({ tileId, visualization }),
        openModal: (tileId: TileId, tabId?: string) => ({ tileId, tabId }),
        closeModal: true,
        setModalTab: (tabId: string) => ({ tabId }),
        setStripeConnected: (connected: boolean) => ({ connected }),
        connectStripe: true,
    }),

    reducers({
        productTab: [
            ProductTab.OVERVIEW as ProductTab,
            {
                setProductTab: (_, { tab }) => tab,
            },
        ],
        dateRange: [
            {
                dateFrom: dayjs().subtract(30, 'day').format('YYYY-MM-DD'),
                dateTo: dayjs().format('YYYY-MM-DD'),
            } as { dateFrom: string | null; dateTo: string | null },
            {
                setDateRange: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
            },
        ],
        tileVisualizations: [
            {} as Record<TileId, TileVisualizationOption>,
            {
                setTileVisualization: (state, { tileId, visualization }) => ({
                    ...state,
                    [tileId]: visualization,
                }),
            },
        ],
        modalTileId: [
            null as TileId | null,
            {
                openModal: (_, { tileId }) => tileId,
                closeModal: () => null,
            },
        ],
        modalTabId: [
            null as string | null,
            {
                openModal: (_, { tabId }) => tabId || null,
                setModalTab: (_, { tabId }) => tabId,
                closeModal: () => null,
            },
        ],
    }),
    selectors({
        isStripeConnected: [
            (s) => [s.dataWarehouseSources],
            (dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null): boolean => {
                return !!dataWarehouseSources?.results.some(
                    (source: ExternalDataSource) => source.source_type === 'Stripe' && source.status === 'connected'
                )
            },
        ],
        tiles: [
            (s) => [s.productTab, s.dateRange],
            (productTab, dateRange): Tile[] => {
                switch (productTab) {
                    case ProductTab.OVERVIEW:
                        return [
                            {
                                kind: 'query',
                                tileId: TileId.ANNUAL_RUN_RATE,
                                title: 'Annual Run Rate',
                                layout: {
                                    colSpanClassName: 'md:col-span-1',
                                },
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: 'stripe_annual_run_rate',
                                                name: 'Annual Run Rate',
                                            },
                                        ],
                                        trendsFilter: {
                                            display: ChartDisplayType.BoldNumber,
                                        },
                                        dateRange: {
                                            date_from: dateRange.dateFrom,
                                            date_to: dateRange.dateTo,
                                        } as DateRange,
                                    },
                                },
                                canOpenModal: true,
                                canOpenInsight: true,
                            },
                            {
                                kind: 'query',
                                tileId: TileId.CUSTOMER_CHURN_RATE,
                                title: 'Customer Churn Rate',
                                layout: {
                                    colSpanClassName: 'md:col-span-1',
                                },
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: 'stripe_customer_churn_rate',
                                                name: 'Customer Churn Rate',
                                            },
                                        ],
                                        trendsFilter: {
                                            display: ChartDisplayType.BoldNumber,
                                        },
                                        dateRange: {
                                            date_from: dateRange.dateFrom,
                                            date_to: dateRange.dateTo,
                                        } as DateRange,
                                    },
                                },
                                canOpenModal: true,
                                canOpenInsight: true,
                            },
                            {
                                kind: 'query',
                                tileId: TileId.AVERAGE_REVENUE_PER_ACCOUNT,
                                title: 'Average Revenue Per Account',
                                layout: {
                                    colSpanClassName: 'md:col-span-1',
                                },
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: 'stripe_average_revenue_per_account',
                                                name: 'Average Revenue Per Account',
                                            },
                                        ],
                                        trendsFilter: {
                                            display: ChartDisplayType.BoldNumber,
                                        },
                                        dateRange: {
                                            date_from: dateRange.dateFrom,
                                            date_to: dateRange.dateTo,
                                        } as DateRange,
                                    },
                                },
                                canOpenModal: true,
                                canOpenInsight: true,
                            },
                            {
                                kind: 'query',
                                tileId: TileId.GROSS_MRR_CHURN_RATE,
                                title: 'Gross MRR Churn Rate',
                                layout: {
                                    colSpanClassName: 'md:col-span-1',
                                },
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: 'stripe_gross_mrr_churn_rate',
                                                name: 'Gross MRR Churn Rate',
                                            },
                                        ],
                                        trendsFilter: {
                                            display: ChartDisplayType.BoldNumber,
                                        },
                                        dateRange: {
                                            date_from: dateRange.dateFrom,
                                            date_to: dateRange.dateTo,
                                        } as DateRange,
                                    },
                                },
                                canOpenModal: true,
                                canOpenInsight: true,
                            },
                            {
                                kind: 'query',
                                tileId: TileId.LTV,
                                title: 'Customer Lifetime Value',
                                layout: {
                                    colSpanClassName: 'md:col-span-1',
                                },
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: 'stripe_customer_lifetime_value',
                                                name: 'Customer Lifetime Value',
                                            },
                                        ],
                                        trendsFilter: {
                                            display: ChartDisplayType.BoldNumber,
                                        },
                                        dateRange: {
                                            date_from: dateRange.dateFrom,
                                            date_to: dateRange.dateTo,
                                        } as DateRange,
                                    },
                                },
                                canOpenModal: true,
                                canOpenInsight: true,
                            },
                            {
                                kind: 'query',
                                tileId: TileId.NET_MRR_CHURN_RATE,
                                title: 'Net MRR Churn Rate',
                                layout: {
                                    colSpanClassName: 'md:col-span-1',
                                },
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: 'stripe_net_mrr_churn_rate',
                                                name: 'Net MRR Churn Rate',
                                            },
                                        ],
                                        trendsFilter: {
                                            display: ChartDisplayType.BoldNumber,
                                        },
                                        dateRange: {
                                            date_from: dateRange.dateFrom,
                                            date_to: dateRange.dateTo,
                                        } as DateRange,
                                    },
                                },
                                canOpenModal: true,
                                canOpenInsight: true,
                            },
                            {
                                kind: 'query',
                                tileId: TileId.AVERAGE_SALE_PRICE,
                                title: 'Average Sale Price',
                                layout: {
                                    colSpanClassName: 'md:col-span-1',
                                },
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: 'stripe_average_sale_price',
                                                name: 'Average Sale Price',
                                            },
                                        ],
                                        trendsFilter: {
                                            display: ChartDisplayType.BoldNumber,
                                        },
                                        dateRange: {
                                            date_from: dateRange.dateFrom,
                                            date_to: dateRange.dateTo,
                                        } as DateRange,
                                    },
                                },
                                canOpenModal: true,
                                canOpenInsight: true,
                            },
                            {
                                kind: 'query',
                                tileId: TileId.NET_CASH_FLOW,
                                title: 'Net Cash Flow',
                                layout: {
                                    colSpanClassName: 'md:col-span-1',
                                },
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: 'stripe_net_cash_flow',
                                                name: 'Net Cash Flow',
                                            },
                                        ],
                                        trendsFilter: {
                                            display: ChartDisplayType.BoldNumber,
                                        },
                                        dateRange: {
                                            date_from: dateRange.dateFrom,
                                            date_to: dateRange.dateTo,
                                        } as DateRange,
                                    },
                                },
                                canOpenModal: true,
                                canOpenInsight: true,
                            },
                            {
                                kind: 'query',
                                tileId: TileId.MRR,
                                title: 'Monthly Recurring Revenue',
                                layout: {
                                    colSpanClassName: 'md:col-span-2',
                                },
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: 'stripe_mrr_over_time',
                                                name: 'MRR',
                                            },
                                        ],
                                        interval: 'day',
                                        trendsFilter: {
                                            display: ChartDisplayType.ActionsLineGraph,
                                        },
                                        dateRange: {
                                            date_from: dateRange.dateFrom,
                                            date_to: dateRange.dateTo,
                                        } as DateRange,
                                    },
                                },
                                canOpenModal: true,
                                canOpenInsight: true,
                            },
                            {
                                kind: 'query',
                                tileId: TileId.SUBSCRIPTIONS,
                                title: 'Subscribers',
                                layout: {
                                    colSpanClassName: 'md:col-span-2',
                                },
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: 'stripe_subscribers_over_time',
                                                name: 'Subscribers',
                                            },
                                        ],
                                        interval: 'day',
                                        trendsFilter: {
                                            display: ChartDisplayType.ActionsLineGraph,
                                        },
                                        dateRange: {
                                            date_from: dateRange.dateFrom,
                                            date_to: dateRange.dateTo,
                                        } as DateRange,
                                    },
                                },
                                canOpenModal: true,
                                canOpenInsight: true,
                            },
                            {
                                kind: 'query',
                                tileId: TileId.MRR,
                                title: 'Monthly Recurring Revenue',
                                layout: {
                                    colSpanClassName: 'md:col-span-1',
                                },
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: 'stripe_mrr',
                                                name: 'MRR',
                                            },
                                        ],
                                        interval: 'month',
                                        trendsFilter: {
                                            display: ChartDisplayType.ActionsLineGraph,
                                        },
                                        dateRange: {
                                            date_from: dateRange.dateFrom,
                                            date_to: dateRange.dateTo,
                                        } as DateRange,
                                    },
                                },
                                canOpenModal: true,
                                canOpenInsight: true,
                            },
                            {
                                kind: 'query',
                                tileId: TileId.ARR,
                                title: 'Annual Recurring Revenue',
                                layout: {
                                    colSpanClassName: 'md:col-span-1',
                                },
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: 'stripe_arr',
                                                name: 'ARR',
                                            },
                                        ],
                                        interval: 'month',
                                        trendsFilter: {
                                            display: ChartDisplayType.ActionsLineGraph,
                                        },
                                        dateRange: {
                                            date_from: dateRange.dateFrom,
                                            date_to: dateRange.dateTo,
                                        } as DateRange,
                                    },
                                },
                                canOpenModal: true,
                                canOpenInsight: true,
                            },
                            {
                                kind: 'churn',
                                tileId: TileId.CHURN,
                                title: 'Customer Churn',
                                layout: {
                                    colSpanClassName: 'md:col-span-2',
                                },
                            },
                            {
                                kind: 'query',
                                tileId: TileId.PAYMENT_METHODS,
                                title: 'Payment Methods',
                                layout: {
                                    colSpanClassName: 'md:col-span-1',
                                },
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.FunnelsQuery,
                                        series: [
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: 'stripe_payment_method',
                                                name: 'Payment Methods',
                                            },
                                        ],
                                        funnelsFilter: {
                                            breakdownAttributionType: BreakdownAttributionType.FirstTouch,
                                        },
                                        dateRange: {
                                            date_from: dateRange.dateFrom,
                                            date_to: dateRange.dateTo,
                                        } as DateRange,
                                    },
                                },
                                canOpenModal: true,
                                canOpenInsight: true,
                            },
                        ]
                    case ProductTab.SUBSCRIPTIONS:
                        return [
                            {
                                kind: 'tabs',
                                tileId: TileId.SUBSCRIPTIONS,
                                layout: {
                                    colSpanClassName: 'md:col-span-2',
                                },
                                activeTabId: 'active',
                                setTabId: () => {},
                                tabs: [
                                    {
                                        id: 'active',
                                        title: 'Active Subscriptions',
                                        linkText: 'Active',
                                        query: {
                                            kind: NodeKind.DataTableNode,
                                            source: {
                                                kind: NodeKind.HogQLQuery,
                                                query: "SELECT subscription_id, plan_name, amount, status, created_at, current_period_end FROM stripe_subscriptions WHERE status = 'active' ORDER BY created_at DESC LIMIT 100",
                                            },
                                        },
                                        canOpenModal: true,
                                        canOpenInsight: true,
                                    },
                                    {
                                        id: 'canceled',
                                        title: 'Canceled Subscriptions',
                                        linkText: 'Canceled',
                                        query: {
                                            kind: NodeKind.DataTableNode,
                                            source: {
                                                kind: NodeKind.HogQLQuery,
                                                query: "SELECT subscription_id, plan_name, amount, status, created_at, canceled_at FROM stripe_subscriptions WHERE status = 'canceled' ORDER BY canceled_at DESC LIMIT 100",
                                            },
                                        },
                                        canOpenModal: true,
                                        canOpenInsight: true,
                                    },
                                    {
                                        id: 'past_due',
                                        title: 'Past Due Subscriptions',
                                        linkText: 'Past Due',
                                        query: {
                                            kind: NodeKind.DataTableNode,
                                            source: {
                                                kind: NodeKind.HogQLQuery,
                                                query: "SELECT subscription_id, plan_name, amount, status, created_at, current_period_end FROM stripe_subscriptions WHERE status = 'past_due' ORDER BY current_period_end DESC LIMIT 100",
                                            },
                                        },
                                        canOpenModal: true,
                                        canOpenInsight: true,
                                    },
                                ],
                            },
                            {
                                kind: 'query',
                                tileId: TileId.REVENUE,
                                title: 'Revenue by Plan',
                                layout: {
                                    colSpanClassName: 'md:col-span-2',
                                },
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: 'stripe_subscription_created',
                                                name: 'Subscription Revenue',
                                            },
                                        ],
                                        interval: 'month',
                                        trendsFilter: {
                                            display: ChartDisplayType.ActionsLineGraph,
                                        },
                                        dateRange: {
                                            date_from: dateRange.dateFrom,
                                            date_to: dateRange.dateTo,
                                        } as DateRange,
                                    },
                                },
                                canOpenModal: true,
                                canOpenInsight: true,
                            },
                        ]
                    case ProductTab.CUSTOMERS:
                        return [
                            {
                                kind: 'customers',
                                tileId: TileId.CUSTOMERS,
                                title: 'Customer List',
                                layout: {
                                    colSpanClassName: 'md:col-span-2',
                                },
                            },
                            {
                                kind: 'query',
                                tileId: TileId.LTV,
                                title: 'Customer Lifetime Value',
                                layout: {
                                    colSpanClassName: 'md:col-span-1',
                                },
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: 'stripe_ltv',
                                                name: 'LTV',
                                            },
                                        ],
                                        interval: 'month',
                                        trendsFilter: {
                                            display: ChartDisplayType.ActionsLineGraph,
                                        },
                                        dateRange: {
                                            date_from: dateRange.dateFrom,
                                            date_to: dateRange.dateTo,
                                        } as DateRange,
                                    },
                                },
                                canOpenModal: true,
                                canOpenInsight: true,
                            },
                        ]
                    default:
                        return []
                }
            },
        ],
        getNewInsightUrl: [
            () => [],
            (): ((tileId: TileId, tabId?: string) => string) => {
                return (tileId: TileId, tabId?: string) => {
                    return `/insights/new?source=revenue_analytics&tile=${tileId}${tabId ? `&tab=${tabId}` : ''}`
                }
            },
        ],
    }),
])

// Helper function to get a new insight URL for a tile
export function getNewInsightUrl(tileId: TileId, tabId?: string): string | undefined {
    // This would be implemented to generate URLs for opening tiles as insights
    return `/insights/new?source=revenue_analytics&tile=${tileId}${tabId ? `&tab=${tabId}` : ''}`
}
