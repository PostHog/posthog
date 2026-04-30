import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { isNotNil } from 'lib/utils'

import {
    EventsNode,
    GroupNode,
    NodeKind,
    TrendsFilter,
    WebAnalyticsPropertyFilter,
    WebAnalyticsPropertyFilters,
} from '~/queries/schema/schema-general'
import {
    BaseMathType,
    BreakdownType,
    ChartDisplayType,
    FilterLogicalOperator,
    InsightLogicProps,
    PropertyFilterBaseValue,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import type { botAnalyticsLogicType } from './botAnalyticsLogicType'
import {
    BOT_ANALYTICS_EVENTS,
    INITIAL_DATE_FROM,
    INITIAL_DATE_TO,
    INITIAL_INTERVAL,
    INITIAL_WEB_ANALYTICS_FILTER,
    TabsTileTab,
    TileId,
    WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
    WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
    WebAnalyticsTile,
    loadPriorityMap,
} from './common'
import { getDashboardItemId } from './insightsUtils'
import { webAnalyticsLogic } from './webAnalyticsLogic'

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
// Distinct prefix from webAnalyticsFilterLogic so bot-tab filters don't collide with the regular tab.
const persistConfig = { persist: true, prefix: `${teamId}__bot_` }

export const botAnalyticsLogic = kea<botAnalyticsLogicType>([
    path(['scenes', 'webAnalytics', 'botAnalyticsLogic']),
    connect(() => ({
        values: [webAnalyticsLogic, ['dateFilter', 'shouldFilterTestAccounts as filterTestAccounts']],
    })),
    actions({
        setBotAnalyticsFilters: (filters: WebAnalyticsPropertyFilters) => ({ filters }),
        toggleBotAnalyticsFilter: (
            type: PropertyFilterType.Event | PropertyFilterType.Person | PropertyFilterType.Session,
            key: string,
            value: string | number | null
        ) => ({ type, key, value }),
        clearBotAnalyticsFilters: true,
        setBotTrendsTab: (tab: string) => ({ tab }),
    }),
    reducers({
        rawBotAnalyticsFilters: [
            INITIAL_WEB_ANALYTICS_FILTER,
            persistConfig,
            {
                setBotAnalyticsFilters: (_, { filters }) => filters,
                clearBotAnalyticsFilters: () => INITIAL_WEB_ANALYTICS_FILTER,
                // Mirror webAnalyticsFilterLogic.togglePropertyFilter add/merge/IsNotSet semantics.
                toggleBotAnalyticsFilter: (oldFilters, { key, value, type }): WebAnalyticsPropertyFilters => {
                    if (value === null) {
                        const isNotSetFilterExists = oldFilters.some(
                            (f) => f.type === type && f.key === key && f.operator === PropertyOperator.IsNotSet
                        )
                        if (isNotSetFilterExists) {
                            return oldFilters.filter(
                                (f) => !(f.type === type && f.key === key && f.operator === PropertyOperator.IsNotSet)
                            )
                        }
                        return [
                            ...oldFilters,
                            {
                                type,
                                key,
                                operator: PropertyOperator.IsNotSet,
                            },
                        ]
                    }

                    const similarFilterExists = oldFilters.some(
                        (f) => f.type === type && f.key === key && f.operator === PropertyOperator.Exact
                    )

                    if (similarFilterExists) {
                        return oldFilters
                            .map((f: WebAnalyticsPropertyFilter) => {
                                if (
                                    f.key !== key ||
                                    f.type !== type ||
                                    ![PropertyOperator.Exact, PropertyOperator.IsNotSet].includes(f.operator)
                                ) {
                                    return f
                                }
                                const oldValue = (Array.isArray(f.value) ? f.value : [f.value]).filter(isNotNil)
                                let newValue: PropertyFilterBaseValue[]
                                if (oldValue.includes(value)) {
                                    if (oldValue.length > 1) {
                                        newValue = [value]
                                    } else {
                                        return null
                                    }
                                } else {
                                    newValue = [...oldValue, value]
                                }
                                return {
                                    type: PropertyFilterType.Event,
                                    key,
                                    operator: PropertyOperator.Exact,
                                    value: newValue,
                                } as const
                            })
                            .filter(isNotNil)
                    }

                    return [
                        ...oldFilters,
                        {
                            type,
                            key,
                            value,
                            operator: PropertyOperator.Exact,
                        },
                    ]
                },
            },
        ],
        _botTrendsTab: [
            null as string | null,
            persistConfig,
            {
                setBotTrendsTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors(({ actions }) => ({
        botTrendsTab: [(s) => [s._botTrendsTab], (tab: string | null) => tab || 'crawler'],
        botFilters: [
            (s) => [s.rawBotAnalyticsFilters],
            (rawBotAnalyticsFilters: WebAnalyticsPropertyFilters): WebAnalyticsPropertyFilters => [
                // User-provided filters first, then the forced bot scope.
                ...rawBotAnalyticsFilters.filter((f) => 'key' in f && f.key !== '$virt_is_bot'),
                {
                    key: '$virt_is_bot',
                    value: ['true'],
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
                {
                    key: '$virt_bot_name',
                    value: [''],
                    operator: PropertyOperator.IsNot,
                    type: PropertyFilterType.Event,
                },
            ],
        ],
        tiles: [
            (s) => [s.dateFilter, s.filterTestAccounts, s.botTrendsTab, s.botFilters],
            (dateFilter, filterTestAccounts, botTrendsTab, botFilters): WebAnalyticsTile[] => {
                const dateRange = { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo }
                const interval = dateFilter.interval

                const createInsightProps = (tile: TileId, tab?: string): InsightLogicProps => ({
                    dashboardItemId: getDashboardItemId(tile, tab, false),
                    loadPriority: loadPriorityMap[tile],
                    dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
                })

                const botTrendsNodes: EventsNode[] = BOT_ANALYTICS_EVENTS.map((event) => ({
                    event,
                    kind: NodeKind.EventsNode as const,
                    math: BaseMathType.TotalCount,
                    name: event,
                }))
                // Combine bot events into a single "Requests" series so the tooltip shows one
                // unified value per breakdown bucket instead of one column per underlying event.
                const botTrendsSeries: GroupNode[] = [
                    {
                        kind: NodeKind.GroupNode,
                        name: BOT_ANALYTICS_EVENTS.join(', '),
                        custom_name: 'Requests',
                        operator: FilterLogicalOperator.Or,
                        nodes: botTrendsNodes,
                        math: BaseMathType.TotalCount,
                    },
                ]

                const createBotTrendsTab = (
                    id: string,
                    title: string,
                    breakdown: string,
                    breakdownType: BreakdownType
                ): TabsTileTab => ({
                    id,
                    title,
                    linkText: title,
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            dateRange,
                            interval: interval ?? 'hour',
                            series: botTrendsSeries,
                            trendsFilter: {
                                display: ChartDisplayType.ActionsLineGraph,
                            } as TrendsFilter,
                            breakdownFilter: {
                                breakdown,
                                breakdown_type: breakdownType,
                            },
                            properties: botFilters,
                            filterTestAccounts,
                            tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                        },
                        hidePersonsModal: true,
                        embedded: true,
                    },
                    insightProps: createInsightProps(TileId.BOT_TRENDS, id),
                    canOpenInsight: true,
                    showIntervalSelect: true,
                })

                const tiles: (WebAnalyticsTile | null)[] = [
                    {
                        kind: 'tabs',
                        tileId: TileId.BOT_TRENDS,
                        layout: {
                            colSpanClassName: 'md:col-span-full',
                        },
                        activeTabId: botTrendsTab,
                        setTabId: actions.setBotTrendsTab,
                        tabs: [
                            createBotTrendsTab('crawler', 'Crawler', '$virt_bot_name', 'event'),
                            createBotTrendsTab('category', 'Category', '$virt_traffic_category', 'event'),
                            createBotTrendsTab('host', 'Host', '$host', 'event'),
                            createBotTrendsTab('path', 'Path', '$pathname', 'event'),
                        ],
                    },
                    {
                        kind: 'query',
                        tileId: TileId.BOT_CRAWLERS,
                        title: 'Crawlers',
                        layout: {
                            colSpanClassName: 'md:col-span-full',
                        },
                        query: {
                            full: true,
                            kind: NodeKind.DataTableNode,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query: `SELECT
    \`$virt_bot_name\` AS "Crawler",
    \`$virt_traffic_category\` AS "Category",
    count() AS "Requests",
    max(timestamp) AS "Last seen"
FROM events
WHERE \`$virt_is_bot\` = true
    AND \`$virt_bot_name\` != ''
    AND event IN (${BOT_ANALYTICS_EVENTS.map((e) => `'${e}'`).join(', ')})
    AND {filters}
GROUP BY "Crawler", "Category"
ORDER BY "Requests" DESC
LIMIT 50`,
                                filters: {
                                    dateRange,
                                    properties: botFilters,
                                    filterTestAccounts,
                                },
                                tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                            },
                            showActions: false,
                            embedded: true,
                        },
                        insightProps: createInsightProps(TileId.BOT_CRAWLERS, 'table'),
                        canOpenModal: false,
                        canOpenInsight: true,
                    },
                    {
                        kind: 'query',
                        tileId: TileId.BOT_PATHS,
                        title: 'Most crawled paths',
                        layout: {
                            colSpanClassName: 'md:col-span-full',
                        },
                        query: {
                            full: true,
                            kind: NodeKind.DataTableNode,
                            source: {
                                kind: NodeKind.HogQLQuery,
                                query: `SELECT
    properties.$pathname AS "Path",
    count(DISTINCT \`$virt_bot_name\`) AS "Crawlers",
    count() AS "Requests",
    max(timestamp) AS "Last seen"
FROM events
WHERE \`$virt_is_bot\` = true
    AND \`$virt_bot_name\` != ''
    AND event IN (${BOT_ANALYTICS_EVENTS.map((e) => `'${e}'`).join(', ')})
    AND properties.$pathname IS NOT NULL
    AND {filters}
GROUP BY "Path"
ORDER BY "Requests" DESC
LIMIT 50`,
                                filters: {
                                    dateRange,
                                    properties: botFilters,
                                    filterTestAccounts,
                                },
                                tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                            },
                            showActions: false,
                            embedded: true,
                        },
                        insightProps: createInsightProps(TileId.BOT_PATHS, 'table'),
                        canOpenModal: false,
                        canOpenInsight: true,
                    },
                ]

                return tiles.filter(isNotNil)
            },
        ],
    })),
    listeners(({ values }) => {
        // Push filter changes into the URL. Only writes /web/bots params; never touches the
        // regular Analytics tab URL because rawWebAnalyticsFilters lives in a separate logic.
        const syncUrl = (): void => {
            if (window.location.pathname !== '/web/bots') {
                return
            }
            const urlParams = new URLSearchParams(router.values.location.search)
            if (values.rawBotAnalyticsFilters.length > 0) {
                urlParams.set('filters', JSON.stringify(values.rawBotAnalyticsFilters))
            } else {
                urlParams.delete('filters')
            }
            const { dateFrom, dateTo, interval } = values.dateFilter
            if (dateFrom !== INITIAL_DATE_FROM || dateTo !== INITIAL_DATE_TO || interval !== INITIAL_INTERVAL) {
                urlParams.set('date_from', dateFrom ?? '')
                urlParams.set('date_to', dateTo ?? '')
                urlParams.set('interval', interval ?? '')
            }
            router.actions.replace(`/web/bots${urlParams.toString() ? '?' + urlParams.toString() : ''}`)
        }
        return {
            setBotAnalyticsFilters: syncUrl,
            toggleBotAnalyticsFilter: syncUrl,
            clearBotAnalyticsFilters: syncUrl,
        }
    }),
])
