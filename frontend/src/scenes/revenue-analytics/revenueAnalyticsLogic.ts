import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { dataWarehouseSceneLogic } from 'scenes/data-warehouse/dataWarehouseSceneLogic'
import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { QuerySchema } from '~/queries/schema/schema-general'

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

export interface RevenueAnalyticsLogicProps { }

export type RevenueAnalyticsLogicType = {
  props: RevenueAnalyticsLogicProps
  key: string
  actions: {
    setProductTab: (tab: ProductTab) => { tab: ProductTab }
    setDateRange: (
      dateFrom: string | null,
      dateTo: string | null
    ) => { dateFrom: string | null; dateTo: string | null }
    setTileVisualization: (
      tileId: TileId,
      visualization: TileVisualizationOption
    ) => { tileId: TileId; visualization: TileVisualizationOption }
    openModal: (tileId: TileId, tabId?: string) => { tileId: TileId; tabId?: string }
    closeModal: () => void
    setModalTab: (tabId: string) => { tabId: string }
    setStripeConnected: (connected: boolean) => { connected: boolean }
    connectStripe: () => void
  }
  reducers: {
    productTab: [ProductTab, { setProductTab: (state: any, { tab }: { tab: ProductTab }) => ProductTab }]
    dateRange: [
      { dateFrom: string | null; dateTo: string | null },
      {
        setDateRange: (
          state: any,
          { dateFrom, dateTo }: { dateFrom: string | null; dateTo: string | null }
        ) => { dateFrom: string | null; dateTo: string | null }
      }
    ]
    tileVisualizations: [
      Record<TileId, TileVisualizationOption>,
      {
        setTileVisualization: (
          state: Record<TileId, TileVisualizationOption>,
          { tileId, visualization }: { tileId: TileId; visualization: TileVisualizationOption }
        ) => Record<TileId, TileVisualizationOption>
      }
    ]
    modalTileId: [
      TileId | null,
      {
        openModal: (state: TileId | null, { tileId }: { tileId: TileId }) => TileId
        closeModal: () => null
      }
    ]
    modalTabId: [
      string | null,
      {
        openModal: (state: string | null, { tabId }: { tabId?: string }) => string | null
        setModalTab: (state: string | null, { tabId }: { tabId: string }) => string
        closeModal: () => null
      }
    ]
    isStripeConnected: [
      boolean,
      {
        setStripeConnected: (state: boolean, { connected }: { connected: boolean }) => boolean
      }
    ]
  }
  loaders: {
    stripeConnectionStatus: {
      __default: { connected: boolean; loading: boolean }
      connectStripe: () => { connected: boolean; loading: boolean }
      loadStripeConnectionStatus: () => { connected: boolean; loading: boolean }
    }
  }
  selectors: {
    tiles: (state: any) => Tile[]
    getNewInsightUrl: (state: any) => (tileId: TileId, tabId?: string) => string
  }
  listeners: {
    connectStripe: () => void
    afterMount: () => void
  }
  values: {
    productTab: ProductTab
    dateRange: { dateFrom: string | null; dateTo: string | null }
    tileVisualizations: Record<TileId, TileVisualizationOption>
    modalTileId: TileId | null
    modalTabId: string | null
    isStripeConnected: boolean
    stripeConnectionStatus: { connected: boolean; loading: boolean }
    tiles: Tile[]
  }
}

export const revenueAnalyticsLogic = kea<revenueAnalyticsLogicType>([
  path(['scenes', 'revenue-analytics', 'revenueAnalyticsLogic']),
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
    isStripeConnected: [
      false,
      {
        setStripeConnected: (_, { connected }) => connected,
      },
    ],
  }),

  loaders(({ values }) => ({
    stripeConnectionStatus: [
      { connected: false, loading: true },
      {
        connectStripe: async () => {
          // Simulate API call to connect Stripe
          await new Promise((resolve) => setTimeout(resolve, 1500))
          return { connected: true, loading: false }
        },
      },
      {
        loadStripeConnectionStatus: async () => {
          // In a real implementation, this would check if Stripe is connected in the data warehouse
          try {
            // This would be an API call to check if Stripe is connected
            // For example: const response = await api.get('api/data_warehouse/sources/stripe/status')

            // For now, we'll simulate a delay and return a mock response
            await new Promise((resolve) => setTimeout(resolve, 500))

            // Check if there's a Stripe source in the data warehouse
            const stripeSource = dataWarehouseSceneLogic.findMounted()?.values.sources.find(
              (source) => source.source_type === 'Stripe' && source.status === 'connected'
            )

            return {
              connected: !!stripeSource,
              loading: false
            }
          } catch (error) {
            console.error('Failed to load Stripe connection status', error)
            return { connected: false, loading: false }
          }
        },
      },
    ],
  })),

  listeners(({ actions }) => ({
    connectStripe: async () => {
      try {
        // Navigate to data warehouse with Stripe source selected
        router.actions.push(urls.dataWarehouse() + '?sourceType=Stripe')

        // Alternatively, we can directly trigger the data warehouse logic to show the Stripe connection modal
        dataWarehouseSceneLogic.findMounted()?.actions.showSourceModal('Stripe')

        // We'll handle the connection status update through a webhook or callback
        // For now, we'll just show a toast message
        lemonToast.info('Connecting to Stripe...')
      } catch (error) {
        lemonToast.error('Failed to open Stripe connection dialog')
        console.error(error)
      }
    },
    afterMount: () => {
      actions.loadStripeConnectionStatus()
    },
  })),

  selectors({
    tiles: [
      (s) => [s.productTab, s.dateRange],
      (productTab, dateRange): Tile[] => {
        const commonProps = {
          dateRange,
        }

        switch (productTab) {
          case ProductTab.OVERVIEW:
            return [
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
                      display: 'ActionsLineGraph',
                    },
                    dateRange,
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
                      display: 'ActionsLineGraph',
                    },
                    dateRange,
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
                      display: 'ActionsLineGraph',
                    },
                    dateRange,
                  },
                },
                canOpenModal: true,
                canOpenInsight: true,
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
                      breakdownBy: 'event',
                      breakdownAttributionType: 'first_touch',
                    },
                    dateRange,
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
                setTabId: (id) => { },
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
                      display: 'ActionsLineGraph',
                      breakdownBy: 'plan',
                    },
                    dateRange,
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
                      display: 'ActionsLineGraph',
                    },
                    dateRange,
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
