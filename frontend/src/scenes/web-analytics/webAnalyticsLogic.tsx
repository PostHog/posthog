import { actions, afterMount, BreakPointFunction, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'
import { windowValues } from 'kea-window-values'
import api from 'lib/api'
import { FEATURE_FLAGS, RETENTION_FIRST_TIME, STALE_EVENT_SECONDS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { Link, PostHogComDocsURL } from 'lib/lemon-ui/Link/Link'
import { featureFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { getDefaultInterval, isNotNil, objectsEqual, updateDatesWithInterval } from 'lib/utils'
import { errorTrackingQuery } from 'scenes/error-tracking/queries'
import { urls } from 'scenes/urls'

import { hogqlQuery } from '~/queries/query'
import {
    ActionConversionGoal,
    ActionsNode,
    AnyEntityNode,
    CompareFilter,
    CustomEventConversionGoal,
    EventsNode,
    NodeKind,
    QuerySchema,
    TrendsFilter,
    WebAnalyticsConversionGoal,
    WebAnalyticsPropertyFilter,
    WebAnalyticsPropertyFilters,
    WebStatsBreakdown,
    WebStatsTableQuery,
} from '~/queries/schema'
import { isWebAnalyticsPropertyFilters } from '~/queries/schema-guards'
import {
    BaseMathType,
    ChartDisplayType,
    EventDefinition,
    EventDefinitionType,
    FilterLogicalOperator,
    InsightLogicProps,
    InsightType,
    IntervalType,
    PluginConfigTypeNew,
    PluginType,
    PropertyDefinition,
    PropertyFilterType,
    PropertyOperator,
    RecordingUniversalFilters,
    RetentionPeriod,
    UniversalFiltersGroupValue,
} from '~/types'

import type { webAnalyticsLogicType } from './webAnalyticsLogicType'

export interface WebTileLayout {
    /** The class has to be spelled out without interpolation, as otherwise Tailwind can't pick it up. */
    colSpanClassName?: `md:col-span-${number}` | 'md:col-span-full'
    /** The class has to be spelled out without interpolation, as otherwise Tailwind can't pick it up. */
    rowSpanClassName?: `md:row-span-${number}`
    /** The class has to be spelled out without interpolation, as otherwise Tailwind can't pick it up. */
    orderWhenLargeClassName?: `xxl:order-${number}`
    className?: string
}

export enum TileId {
    OVERVIEW = 'OVERVIEW',
    GRAPHS = 'GRAPHS',
    PATHS = 'PATHS',
    SOURCES = 'SOURCES',
    DEVICES = 'DEVICES',
    GEOGRAPHY = 'GEOGRAPHY',
    RETENTION = 'RETENTION',
    REPLAY = 'REPLAY',
    ERROR_TRACKING = 'ERROR_TRACKING',
    GOALS = 'GOALS',
}

const loadPriorityMap: Record<TileId, number> = {
    [TileId.OVERVIEW]: 1,
    [TileId.GRAPHS]: 2,
    [TileId.PATHS]: 3,
    [TileId.SOURCES]: 4,
    [TileId.DEVICES]: 5,
    [TileId.GEOGRAPHY]: 6,
    [TileId.RETENTION]: 7,
    [TileId.REPLAY]: 8,
    [TileId.ERROR_TRACKING]: 9,
    [TileId.GOALS]: 10,
}

interface BaseTile {
    tileId: TileId
    layout: WebTileLayout
    docs?: Docs
}

export interface Docs {
    url?: PostHogComDocsURL
    title: string
    description: string | JSX.Element
}
export interface QueryTile extends BaseTile {
    kind: 'query'
    title?: string
    query: QuerySchema
    showIntervalSelect?: boolean
    showPathCleaningControls?: boolean
    insightProps: InsightLogicProps
    canOpenModal: boolean
    canOpenInsight?: boolean
}

export interface TabsTileTab {
    id: string
    title: string
    linkText: string
    query: QuerySchema
    showIntervalSelect?: boolean
    showPathCleaningControls?: boolean
    insightProps: InsightLogicProps
    canOpenModal?: boolean
    canOpenInsight?: boolean
    docs?: Docs
}

export interface TabsTile extends BaseTile {
    kind: 'tabs'
    activeTabId: string
    setTabId: (id: string) => void
    tabs: TabsTileTab[]
}

export interface ReplayTile extends BaseTile {
    kind: 'replay'
}

export interface ErrorTrackingTile extends BaseTile {
    kind: 'error_tracking'
    query: QuerySchema
}

export type WebDashboardTile = QueryTile | TabsTile | ReplayTile | ErrorTrackingTile

export interface WebDashboardModalQuery {
    tileId: TileId
    tabId?: string
    title?: string
    query: QuerySchema
    insightProps: InsightLogicProps
    showIntervalSelect?: boolean
    showPathCleaningControls?: boolean
    canOpenInsight?: boolean
}

export enum GraphsTab {
    UNIQUE_USERS = 'UNIQUE_USERS',
    PAGE_VIEWS = 'PAGE_VIEWS',
    NUM_SESSION = 'NUM_SESSION',
    UNIQUE_CONVERSIONS = 'UNIQUE_CONVERSIONS',
    TOTAL_CONVERSIONS = 'TOTAL_CONVERSIONS',
    CONVERSION_RATE = 'CONVERSION_RATE',
}

export enum SourceTab {
    CHANNEL = 'CHANNEL',
    REFERRING_DOMAIN = 'REFERRING_DOMAIN',
    UTM_SOURCE = 'UTM_SOURCE',
    UTM_MEDIUM = 'UTM_MEDIUM',
    UTM_CAMPAIGN = 'UTM_CAMPAIGN',
    UTM_CONTENT = 'UTM_CONTENT',
    UTM_TERM = 'UTM_TERM',
    UTM_SOURCE_MEDIUM_CAMPAIGN = 'UTM_SOURCE_MEDIUM_CAMPAIGN',
}

export enum DeviceTab {
    BROWSER = 'BROWSER',
    OS = 'OS',
    DEVICE_TYPE = 'DEVICE_TYPE',
}

export enum PathTab {
    PATH = 'PATH',
    INITIAL_PATH = 'INITIAL_PATH',
    END_PATH = 'END_PATH',
    EXIT_CLICK = 'EXIT_CLICK',
}

export enum GeographyTab {
    MAP = 'MAP',
    COUNTRIES = 'COUNTRIES',
    REGIONS = 'REGIONS',
    CITIES = 'CITIES',
    TIMEZONES = 'TIMEZONES',
    LANGUAGES = 'LANGUAGES',
}

export interface WebAnalyticsStatusCheck {
    isSendingPageViews: boolean
    isSendingPageLeaves: boolean
    isSendingPageLeavesScroll: boolean
}

export enum ConversionGoalWarning {
    CustomEventWithNoSessionId = 'CustomEventWithNoSessionId',
}

export const GEOIP_PLUGIN_URLS = [
    'https://github.com/PostHog/posthog-plugin-geoip',
    'https://www.npmjs.com/package/@posthog/geoip-plugin',
]

export const WEB_ANALYTICS_DATA_COLLECTION_NODE_ID = 'web-analytics'

export const initialWebAnalyticsFilter = [] as WebAnalyticsPropertyFilters
const initialDateFrom = '-7d' as string | null
const initialDateTo = null as string | null
const initialInterval = getDefaultInterval(initialDateFrom, initialDateTo)

const getDashboardItemId = (section: TileId, tab: string | undefined, isModal?: boolean): `new-${string}` => {
    // pretend to be a new-AdHoc to get the correct behaviour elsewhere
    return `new-AdHoc.web-analytics.${section}.${tab || 'default'}.${isModal ? 'modal' : 'default'}`
}

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
const persistConfig = { persist: true, prefix: `${teamId}__` }
export const webAnalyticsLogic = kea<webAnalyticsLogicType>([
    path(['scenes', 'webAnalytics', 'webAnalyticsSceneLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setWebAnalyticsFilters: (webAnalyticsFilters: WebAnalyticsPropertyFilters) => ({ webAnalyticsFilters }),
        togglePropertyFilter: (
            type: PropertyFilterType.Event | PropertyFilterType.Person | PropertyFilterType.Session,
            key: string,
            value: string | number | null,
            tabChange?: {
                graphsTab?: string
                sourceTab?: string
                deviceTab?: string
                pathTab?: string
                geographyTab?: string
            }
        ) => ({
            type,
            key,
            value,
            tabChange,
        }),
        setGraphsTab: (tab: string) => ({
            tab,
        }),
        setSourceTab: (tab: string) => ({
            tab,
        }),
        setDeviceTab: (tab: string) => ({
            tab,
        }),
        setPathTab: (tab: string) => ({
            tab,
        }),
        setGeographyTab: (tab: string) => ({ tab }),
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setInterval: (interval: IntervalType) => ({ interval }),
        setDatesAndInterval: (dateFrom: string | null, dateTo: string | null, interval: IntervalType) => ({
            dateFrom,
            dateTo,
            interval,
        }),
        setIsPathCleaningEnabled: (isPathCleaningEnabled: boolean) => ({ isPathCleaningEnabled }),
        setShouldFilterTestAccounts: (shouldFilterTestAccounts: boolean) => ({
            shouldFilterTestAccounts,
        }),
        setShouldStripQueryParams: (shouldStripQueryParams: boolean) => ({
            shouldStripQueryParams,
        }),
        setConversionGoal: (conversionGoal: WebAnalyticsConversionGoal | null) => ({ conversionGoal }),
        openModal: (tileId: TileId, tabId?: string) => {
            return { tileId, tabId }
        },
        closeModal: () => true,
        openAsNewInsight: (tileId: TileId, tabId?: string) => {
            return { tileId, tabId }
        },
        setConversionGoalWarning: (warning: ConversionGoalWarning | null) => ({ warning }),
        setCompareFilter: (compareFilter: CompareFilter) => ({ compareFilter }),
    }),
    reducers({
        webAnalyticsFilters: [
            initialWebAnalyticsFilter,
            persistConfig,
            {
                setWebAnalyticsFilters: (_, { webAnalyticsFilters }) => webAnalyticsFilters,
                togglePropertyFilter: (oldPropertyFilters, { key, value, type }): WebAnalyticsPropertyFilters => {
                    if (value === null) {
                        // if there's already an isNotSet filter, remove it
                        const isNotSetFilterExists = oldPropertyFilters.some(
                            (f) => f.type === type || f.key === key || f.operator === PropertyOperator.IsNotSet
                        )
                        if (isNotSetFilterExists) {
                            return oldPropertyFilters.filter(
                                (f) => f.type !== type || f.key !== key || f.operator !== PropertyOperator.IsNotSet
                            )
                        }
                        return [
                            ...oldPropertyFilters,
                            {
                                type,
                                key,
                                operator: PropertyOperator.IsNotSet,
                            },
                        ]
                    }
                    const similarFilterExists = oldPropertyFilters.some(
                        (f) => f.type === type && f.key === key && f.operator === PropertyOperator.Exact
                    )
                    if (similarFilterExists) {
                        // if there's already a matching property, turn it off or merge them
                        return oldPropertyFilters
                            .map((f) => {
                                if (
                                    f.key !== key ||
                                    f.type !== type ||
                                    ![PropertyOperator.Exact, PropertyOperator.IsNotSet].includes(f.operator)
                                ) {
                                    return f
                                }
                                const oldValue = (Array.isArray(f.value) ? f.value : [f.value]).filter(isNotNil)
                                let newValue: (string | number)[]
                                if (oldValue.includes(value)) {
                                    // If there are multiple values for this filter, reduce that to just the one being clicked
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
                    // no matching property, so add one
                    const newFilter: WebAnalyticsPropertyFilter = {
                        type,
                        key,
                        value,
                        operator: PropertyOperator.Exact,
                    }

                    return [...oldPropertyFilters, newFilter]
                },
            },
        ],
        _graphsTab: [
            null as string | null,
            persistConfig,
            {
                setGraphsTab: (_, { tab }) => tab,
                togglePropertyFilter: (oldTab, { tabChange }) => tabChange?.graphsTab || oldTab,
            },
        ],
        _sourceTab: [
            null as string | null,
            persistConfig,
            {
                setSourceTab: (_, { tab }) => tab,
                togglePropertyFilter: (oldTab, { tabChange }) => tabChange?.sourceTab || oldTab,
            },
        ],
        _deviceTab: [
            null as string | null,
            persistConfig,
            {
                setDeviceTab: (_, { tab }) => tab,
                togglePropertyFilter: (oldTab, { tabChange }) => tabChange?.deviceTab || oldTab,
            },
        ],
        _pathTab: [
            null as string | null,
            persistConfig,
            {
                setPathTab: (_, { tab }) => tab,
                togglePropertyFilter: (oldTab, { tabChange }) => tabChange?.pathTab || oldTab,
            },
        ],
        _geographyTab: [
            null as string | null,
            persistConfig,
            {
                setGeographyTab: (_, { tab }) => tab,
                togglePropertyFilter: (oldTab, { tabChange }) => tabChange?.geographyTab || oldTab,
            },
        ],
        isPathCleaningEnabled: [
            null as boolean | null,
            persistConfig,
            {
                setIsPathCleaningEnabled: (_, { isPathCleaningEnabled }) => isPathCleaningEnabled,
            },
        ],
        _modalTileAndTab: [
            null as { tileId: TileId; tabId?: string } | null,
            {
                openModal: (_, { tileId, tabId }) => ({
                    tileId,
                    tabId,
                }),
                closeModal: () => null,
            },
        ],
        dateFilter: [
            {
                dateFrom: initialDateFrom,
                dateTo: initialDateTo,
                interval: initialInterval,
            },
            persistConfig,
            {
                setDates: (_, { dateTo, dateFrom }) => ({
                    dateTo,
                    dateFrom,
                    interval: getDefaultInterval(dateFrom, dateTo),
                }),
                setInterval: ({ dateFrom: oldDateFrom, dateTo: oldDateTo }, { interval }) => {
                    const { dateFrom, dateTo } = updateDatesWithInterval(interval, oldDateFrom, oldDateTo)
                    return {
                        dateTo,
                        dateFrom,
                        interval,
                    }
                },
                setDatesAndInterval: (_, { dateTo, dateFrom, interval }) => {
                    if (!dateFrom && !dateTo) {
                        dateFrom = initialDateFrom
                        dateTo = initialDateTo
                    }
                    return {
                        dateTo,
                        dateFrom,
                        interval: interval || getDefaultInterval(dateFrom, dateTo),
                    }
                },
            },
        ],
        shouldFilterTestAccounts: [
            false as boolean,
            persistConfig,
            {
                setShouldFilterTestAccounts: (_, { shouldFilterTestAccounts }) => shouldFilterTestAccounts,
            },
        ],
        shouldStripQueryParams: [
            false as boolean,
            persistConfig,
            {
                setShouldStripQueryParams: (_, { shouldStripQueryParams }) => shouldStripQueryParams,
            },
        ],
        conversionGoal: [
            null as WebAnalyticsConversionGoal | null,
            persistConfig,
            {
                setConversionGoal: (_, { conversionGoal }) => conversionGoal,
            },
        ],
        conversionGoalWarning: [
            null as ConversionGoalWarning | null,
            {
                setConversionGoalWarning: (_, { warning }) => warning,
            },
        ],
        compareFilter: [
            { compare: true } as CompareFilter,
            persistConfig,
            {
                setCompareFilter: (_, { compareFilter }) => compareFilter,
            },
        ],
    }),
    selectors(({ actions, values }) => ({
        graphsTab: [(s) => [s._graphsTab], (graphsTab: string | null) => graphsTab || GraphsTab.UNIQUE_USERS],
        sourceTab: [(s) => [s._sourceTab], (sourceTab: string | null) => sourceTab || SourceTab.CHANNEL],
        deviceTab: [(s) => [s._deviceTab], (deviceTab: string | null) => deviceTab || DeviceTab.DEVICE_TYPE],
        pathTab: [(s) => [s._pathTab], (pathTab: string | null) => pathTab || PathTab.PATH],
        geographyTab: [(s) => [s._geographyTab], (geographyTab: string | null) => geographyTab || GeographyTab.MAP],
        tabs: [
            (s) => [
                s.graphsTab,
                s.sourceTab,
                s.deviceTab,
                s.pathTab,
                s.geographyTab,
                () => values.shouldShowGeographyTile,
            ],
            (graphsTab, sourceTab, deviceTab, pathTab, geographyTab, shouldShowGeographyTile) => ({
                graphsTab,
                sourceTab,
                deviceTab,
                pathTab,
                geographyTab,
                shouldShowGeographyTile,
            }),
        ],
        controls: [
            (s) => [s.isPathCleaningEnabled, s.shouldFilterTestAccounts, s.shouldStripQueryParams],
            (isPathCleaningEnabled, filterTestAccounts, shouldStripQueryParams) => ({
                isPathCleaningEnabled,
                filterTestAccounts,
                shouldStripQueryParams,
            }),
        ],
        filters: [
            (s) => [s.webAnalyticsFilters, s.replayFilters, s.dateFilter, s.compareFilter, () => values.conversionGoal],
            (webAnalyticsFilters, replayFilters, dateFilter, compareFilter, conversionGoal) => ({
                webAnalyticsFilters,
                replayFilters,
                dateFilter,
                compareFilter,
                conversionGoal,
            }),
        ],
        tiles: [
            (s) => [s.tabs, s.controls, s.filters, () => values.featureFlags, () => values.isGreaterThanMd],
            (
                { graphsTab, sourceTab, deviceTab, pathTab, geographyTab, shouldShowGeographyTile },
                { isPathCleaningEnabled, filterTestAccounts, shouldStripQueryParams },
                {
                    webAnalyticsFilters,
                    replayFilters,
                    dateFilter: { dateFrom, dateTo, interval },
                    conversionGoal,
                    compareFilter,
                },
                featureFlags,
                isGreaterThanMd
            ): WebDashboardTile[] => {
                const dateRange = {
                    date_from: dateFrom,
                    date_to: dateTo,
                }

                const sampling = {
                    enabled: false,
                    forceSamplingRate: { numerator: 1, denominator: 10 },
                }

                const createInsightProps = (tile: TileId, tab?: string): InsightLogicProps => {
                    return {
                        dashboardItemId: getDashboardItemId(tile, tab, false),
                        loadPriority: loadPriorityMap[tile],
                        dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
                    }
                }

                const uniqueUserSeries: EventsNode = {
                    event: '$pageview',
                    kind: NodeKind.EventsNode,
                    math: BaseMathType.UniqueUsers,
                    name: 'Pageview',
                    custom_name: 'Unique visitors',
                }
                const pageViewsSeries = {
                    ...uniqueUserSeries,
                    math: BaseMathType.TotalCount,
                    custom_name: 'Page views',
                }
                const sessionsSeries = {
                    ...uniqueUserSeries,
                    math: BaseMathType.UniqueSessions,
                    custom_name: 'Sessions',
                }
                const uniqueConversionsSeries: ActionsNode | EventsNode | undefined = !conversionGoal
                    ? undefined
                    : 'actionId' in conversionGoal
                    ? {
                          kind: NodeKind.ActionsNode,
                          id: conversionGoal.actionId,
                          math: BaseMathType.UniqueUsers,
                          name: 'Unique conversions',
                          custom_name: 'Unique conversions',
                      }
                    : {
                          kind: NodeKind.EventsNode,
                          event: conversionGoal.customEventName,
                          math: BaseMathType.UniqueUsers,
                          name: 'Unique conversions',
                          custom_name: 'Unique conversions',
                      }
                const totalConversionSeries = uniqueConversionsSeries
                    ? {
                          ...uniqueConversionsSeries,
                          math: BaseMathType.TotalCount,
                          name: 'Total conversions',
                          custom_name: 'Total conversions',
                      }
                    : undefined

                const createGraphsTrendsTab = (
                    id: GraphsTab,
                    title: string,
                    linkText: string,
                    series: AnyEntityNode[],
                    trendsFilter?: Partial<TrendsFilter>
                ): TabsTileTab => ({
                    id,
                    title,
                    linkText,
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            dateRange,
                            interval,
                            series: series,
                            trendsFilter: {
                                display: ChartDisplayType.ActionsLineGraph,
                                ...trendsFilter,
                            },
                            compareFilter,
                            filterTestAccounts,
                            conversionGoal: featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_CONVERSION_GOAL_FILTERS]
                                ? conversionGoal
                                : undefined,
                            properties: webAnalyticsFilters,
                        },
                        hidePersonsModal: true,
                        embedded: true,
                    },
                    showIntervalSelect: true,
                    insightProps: createInsightProps(TileId.GRAPHS, id),
                    canOpenInsight: true,
                })

                const createTableTab = (
                    tileId: TileId,
                    tabId: string,
                    title: string,
                    linkText: string,
                    breakdownBy: WebStatsBreakdown,
                    source?: Partial<WebStatsTableQuery>,
                    tab?: Partial<TabsTileTab>
                ): TabsTileTab => {
                    const columns = ['breakdown_value', 'visitors', 'views']
                    if (source?.includeBounceRate) {
                        columns.push('bounce_rate')
                    }

                    return {
                        id: tabId,
                        title,
                        linkText,
                        query: {
                            full: true,
                            kind: NodeKind.DataTableNode,
                            source: {
                                kind: NodeKind.WebStatsTableQuery,
                                properties: webAnalyticsFilters,
                                breakdownBy: breakdownBy,
                                dateRange,
                                sampling,
                                compareFilter,
                                limit: 10,
                                filterTestAccounts,
                                conversionGoal: featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_CONVERSION_GOAL_FILTERS]
                                    ? conversionGoal
                                    : undefined,
                                ...(source || {}),
                            },
                            embedded: false,
                            columns,
                        },
                        insightProps: createInsightProps(tileId, tabId),
                        canOpenModal: true,
                        ...(tab || {}),
                    }
                }

                const allTiles: (WebDashboardTile | null)[] = [
                    {
                        kind: 'query',
                        tileId: TileId.OVERVIEW,
                        layout: {
                            colSpanClassName: 'md:col-span-full',
                            orderWhenLargeClassName: 'xxl:order-0',
                        },
                        query: {
                            kind: NodeKind.WebOverviewQuery,
                            properties: webAnalyticsFilters,
                            dateRange,
                            sampling,
                            compareFilter,
                            filterTestAccounts,
                            conversionGoal,
                            includeLCPScore: featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_LCP_SCORE] ? true : undefined,
                        },
                        insightProps: createInsightProps(TileId.OVERVIEW),
                        canOpenModal: false,
                    },
                    {
                        kind: 'tabs',
                        tileId: TileId.GRAPHS,
                        layout: {
                            colSpanClassName: `md:col-span-2`,
                            orderWhenLargeClassName: 'xxl:order-1',
                        },
                        activeTabId: graphsTab,
                        setTabId: actions.setGraphsTab,
                        tabs: (
                            [
                                createGraphsTrendsTab(GraphsTab.UNIQUE_USERS, 'Unique visitors', 'Visitors', [
                                    uniqueUserSeries,
                                ]),
                                !conversionGoal
                                    ? createGraphsTrendsTab(GraphsTab.PAGE_VIEWS, 'Page views', 'Views', [
                                          pageViewsSeries,
                                      ])
                                    : null,
                                !conversionGoal
                                    ? createGraphsTrendsTab(GraphsTab.NUM_SESSION, 'Unique sessions', 'Sessions', [
                                          sessionsSeries,
                                      ])
                                    : null,
                                conversionGoal && uniqueConversionsSeries
                                    ? createGraphsTrendsTab(
                                          GraphsTab.UNIQUE_CONVERSIONS,
                                          'Unique conversions',
                                          'Unique conversions',
                                          [uniqueConversionsSeries]
                                      )
                                    : null,
                                conversionGoal && totalConversionSeries
                                    ? createGraphsTrendsTab(
                                          GraphsTab.TOTAL_CONVERSIONS,
                                          'Total conversions',
                                          'Total conversions',
                                          [totalConversionSeries]
                                      )
                                    : null,
                                conversionGoal && uniqueUserSeries && uniqueConversionsSeries
                                    ? createGraphsTrendsTab(
                                          GraphsTab.CONVERSION_RATE,
                                          'Conversion rate',
                                          'Conversion rate',
                                          [uniqueConversionsSeries, uniqueUserSeries],
                                          {
                                              formula: 'A / B',
                                              aggregationAxisFormat: 'percentage_scaled',
                                          }
                                      )
                                    : null,
                            ] as (TabsTileTab | null)[]
                        ).filter(isNotNil),
                    },
                    {
                        kind: 'tabs',
                        tileId: TileId.PATHS,
                        layout: {
                            colSpanClassName: `md:col-span-2`,
                            orderWhenLargeClassName: 'xxl:order-4',
                        },
                        activeTabId: pathTab,
                        setTabId: actions.setPathTab,
                        tabs: (
                            [
                                createTableTab(
                                    TileId.PATHS,
                                    PathTab.PATH,
                                    'Paths',
                                    'Path',
                                    WebStatsBreakdown.Page,
                                    {
                                        includeScrollDepth: false, // TODO needs some perf work before it can be enabled
                                        includeBounceRate: true,
                                        doPathCleaning: !!isPathCleaningEnabled,
                                    },
                                    {
                                        showPathCleaningControls: true,
                                        docs: {
                                            url: 'https://posthog.com/docs/web-analytics/dashboard#paths',
                                            title: 'Paths',
                                            description: (
                                                <div>
                                                    <p>
                                                        In this view you can validate all of the paths that were
                                                        accessed in your application, regardless of when they were
                                                        accessed through the lifetime of a user session.
                                                    </p>
                                                    {conversionGoal ? (
                                                        <p>
                                                            The conversion rate is the percentage of users who completed
                                                            the conversion goal in this specific path.
                                                        </p>
                                                    ) : (
                                                        <p>
                                                            The{' '}
                                                            <Link to="https://posthog.com/docs/web-analytics/dashboard#bounce-rate">
                                                                bounce rate
                                                            </Link>{' '}
                                                            indicates the percentage of users who left your page
                                                            immediately after visiting without capturing any event.
                                                        </p>
                                                    )}
                                                </div>
                                            ),
                                        },
                                    }
                                ),
                                createTableTab(
                                    TileId.PATHS,
                                    PathTab.INITIAL_PATH,
                                    'Entry paths',
                                    'Entry path',
                                    WebStatsBreakdown.InitialPage,
                                    {
                                        includeBounceRate: true,
                                        includeScrollDepth: false,
                                        doPathCleaning: !!isPathCleaningEnabled,
                                    },
                                    {
                                        showPathCleaningControls: true,
                                        docs: {
                                            url: 'https://posthog.com/docs/web-analytics/dashboard#paths',
                                            title: 'Entry Path',
                                            description: (
                                                <div>
                                                    <p>
                                                        Entry paths are the paths a user session started, i.e. the first
                                                        path they saw when they opened your website.
                                                    </p>
                                                    {conversionGoal && (
                                                        <p>
                                                            The conversion rate is the percentage of users who completed
                                                            the conversion goal after the first path in their session
                                                            being this path.
                                                        </p>
                                                    )}
                                                </div>
                                            ),
                                        },
                                    }
                                ),
                                createTableTab(
                                    TileId.PATHS,
                                    PathTab.END_PATH,
                                    'End paths',
                                    'End path',
                                    WebStatsBreakdown.ExitPage,
                                    {
                                        includeBounceRate: false,
                                        includeScrollDepth: false,
                                        doPathCleaning: !!isPathCleaningEnabled,
                                    },
                                    {
                                        showPathCleaningControls: true,
                                        docs: {
                                            url: 'https://posthog.com/docs/web-analytics/dashboard#paths',
                                            title: 'End Path',
                                            description: (
                                                <div>
                                                    End paths are the last path a user visited before their session
                                                    ended, i.e. the last path they saw before leaving your
                                                    website/closing the browser/turning their computer off.
                                                </div>
                                            ),
                                        },
                                    }
                                ),
                                featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_LAST_CLICK]
                                    ? {
                                          id: PathTab.EXIT_CLICK,
                                          title: 'Outbound link clicks',
                                          linkText: 'Outbound clicks',
                                          query: {
                                              full: true,
                                              kind: NodeKind.DataTableNode,
                                              source: {
                                                  kind: NodeKind.WebExternalClicksTableQuery,
                                                  properties: webAnalyticsFilters,
                                                  dateRange,
                                                  compareFilter,
                                                  sampling,
                                                  limit: 10,
                                                  filterTestAccounts,
                                                  conversionGoal: featureFlags[
                                                      FEATURE_FLAGS.WEB_ANALYTICS_CONVERSION_GOAL_FILTERS
                                                  ]
                                                      ? conversionGoal
                                                      : undefined,
                                                  stripQueryParams: shouldStripQueryParams,
                                              },
                                              embedded: false,
                                              columns: ['url', 'visitors', 'clicks'],
                                          },
                                          insightProps: createInsightProps(TileId.PATHS, PathTab.END_PATH),
                                          canOpenModal: true,
                                          docs: {
                                              title: 'Outbound Clicks',
                                              description: (
                                                  <div>
                                                      You'll be able to verify when someone leaves your website by
                                                      clicking an outbound link (to a separate domain)
                                                  </div>
                                              ),
                                          },
                                      }
                                    : null,
                            ] as (TabsTileTab | undefined)[]
                        ).filter(isNotNil),
                    },
                    {
                        kind: 'tabs',
                        tileId: TileId.SOURCES,
                        layout: {
                            colSpanClassName: `md:col-span-1`,
                            orderWhenLargeClassName: 'xxl:order-2',
                        },
                        activeTabId: sourceTab,
                        setTabId: actions.setSourceTab,
                        tabs: [
                            createTableTab(
                                TileId.SOURCES,
                                SourceTab.CHANNEL,
                                'Channels',
                                'Channel',
                                WebStatsBreakdown.InitialChannelType,
                                {},
                                {
                                    docs: {
                                        url: 'https://posthog.com/docs/data/channel-type',
                                        title: 'Channels',
                                        description: (
                                            <div>
                                                <p>
                                                    Channels are the different sources that bring traffic to your
                                                    website, e.g. Paid Search, Organic Social, Direct, etc.
                                                </p>
                                                {featureFlags[FEATURE_FLAGS.CUSTOM_CHANNEL_TYPE_RULES] && (
                                                    <p>
                                                        You can also{' '}
                                                        <Link
                                                            to={urls.settings(
                                                                'environment-web-analytics',
                                                                'channel-type'
                                                            )}
                                                        >
                                                            create custom channel types
                                                        </Link>
                                                        , allowing you to further categorize your channels.
                                                    </p>
                                                )}

                                                <p>
                                                    Something unexpected? Try the{' '}
                                                    <Link to={urls.sessionAttributionExplorer()}>
                                                        Session attribution explorer
                                                    </Link>
                                                </p>
                                            </div>
                                        ),
                                    },
                                }
                            ),
                            createTableTab(
                                TileId.SOURCES,
                                SourceTab.REFERRING_DOMAIN,
                                'Referrers',
                                'Referring domain',
                                WebStatsBreakdown.InitialReferringDomain,
                                {},
                                {
                                    docs: {
                                        url: 'https://posthog.com/docs/web-analytics/dashboard#referrers-channels-utms',
                                        title: 'Referrers',
                                        description: 'Understand where your users are coming from',
                                    },
                                }
                            ),
                            createTableTab(
                                TileId.SOURCES,
                                SourceTab.UTM_SOURCE,
                                'UTM sources',
                                'UTM source',
                                WebStatsBreakdown.InitialUTMSource,
                                {},
                                {
                                    docs: {
                                        url: 'https://posthog.com/docs/web-analytics/dashboard#utms',
                                        title: 'UTM source',
                                        description: (
                                            <>
                                                Understand where your users are coming from - filtered down by their{' '}
                                                <code>utm_source</code> parameter
                                            </>
                                        ),
                                    },
                                }
                            ),
                            createTableTab(
                                TileId.SOURCES,
                                SourceTab.UTM_MEDIUM,
                                'UTM medium',
                                'UTM medium',
                                WebStatsBreakdown.InitialUTMMedium,
                                {},
                                {
                                    docs: {
                                        url: 'https://posthog.com/docs/web-analytics/dashboard#utms',
                                        title: 'UTM medium',
                                        description: (
                                            <>
                                                Understand where your users are coming from - filtered down by their{' '}
                                                <code>utm_medium</code> parameter
                                            </>
                                        ),
                                    },
                                }
                            ),
                            createTableTab(
                                TileId.SOURCES,
                                SourceTab.UTM_CAMPAIGN,
                                'UTM campaigns',
                                'UTM campaign',
                                WebStatsBreakdown.InitialUTMCampaign,
                                {},
                                {
                                    docs: {
                                        url: 'https://posthog.com/docs/web-analytics/dashboard#utms',
                                        title: 'UTM campaign',
                                        description: (
                                            <>
                                                Understand where your users are coming from - filtered down by their{' '}
                                                <code>utm_campaign</code> parameter
                                            </>
                                        ),
                                    },
                                }
                            ),
                            createTableTab(
                                TileId.SOURCES,
                                SourceTab.UTM_CONTENT,
                                'UTM content',
                                'UTM content',
                                WebStatsBreakdown.InitialUTMContent,
                                {},
                                {
                                    docs: {
                                        url: 'https://posthog.com/docs/web-analytics/dashboard#utms',
                                        title: 'UTM content',
                                        description: (
                                            <>
                                                Understand where your users are coming from - filtered down by their{' '}
                                                <code>utm_content</code> parameter
                                            </>
                                        ),
                                    },
                                }
                            ),
                            createTableTab(
                                TileId.SOURCES,
                                SourceTab.UTM_TERM,
                                'UTM terms',
                                'UTM term',
                                WebStatsBreakdown.InitialUTMTerm,
                                {},
                                {
                                    docs: {
                                        url: 'https://posthog.com/docs/web-analytics/dashboard#utms',
                                        title: 'UTM term',
                                        description: (
                                            <>
                                                Understand where your users are coming from - filtered down by their{' '}
                                                <code>utm_term</code> parameter
                                            </>
                                        ),
                                    },
                                }
                            ),
                            createTableTab(
                                TileId.SOURCES,
                                SourceTab.UTM_SOURCE_MEDIUM_CAMPAIGN,
                                'Source / Medium / Campaign',
                                'UTM s/m/c',
                                WebStatsBreakdown.InitialUTMSourceMediumCampaign,
                                {},
                                {
                                    docs: {
                                        url: 'https://posthog.com/docs/web-analytics/dashboard#utms',
                                        title: 'UTM parameters',
                                        description: (
                                            <>
                                                Understand where your users are coming from - filtered down by a tuple
                                                of their <code>utm_source</code>, <code>utm_medium</code>, and{' '}
                                                <code>utm_campaign</code> parameters
                                            </>
                                        ),
                                    },
                                }
                            ),
                        ],
                    },
                    {
                        kind: 'tabs',
                        tileId: TileId.DEVICES,
                        layout: {
                            colSpanClassName: `md:col-span-1`,
                            orderWhenLargeClassName: 'xxl:order-3',
                        },
                        activeTabId: deviceTab,
                        setTabId: actions.setDeviceTab,
                        tabs: [
                            createTableTab(
                                TileId.DEVICES,
                                DeviceTab.DEVICE_TYPE,
                                'Device type',
                                'Device type',
                                WebStatsBreakdown.DeviceType
                            ),
                            createTableTab(
                                TileId.DEVICES,
                                DeviceTab.BROWSER,
                                'Browsers',
                                'Browser',
                                WebStatsBreakdown.Browser
                            ),
                            createTableTab(TileId.DEVICES, DeviceTab.OS, 'OS', 'OS', WebStatsBreakdown.OS),
                        ],
                    },
                    shouldShowGeographyTile
                        ? {
                              kind: 'tabs',
                              tileId: TileId.GEOGRAPHY,
                              layout: {
                                  colSpanClassName: 'md:col-span-full',
                              },
                              activeTabId: geographyTab || GeographyTab.MAP,
                              setTabId: actions.setGeographyTab,
                              tabs: [
                                  {
                                      id: GeographyTab.MAP,
                                      title: 'World map',
                                      linkText: 'Map',
                                      query: {
                                          kind: NodeKind.InsightVizNode,
                                          source: {
                                              kind: NodeKind.TrendsQuery,
                                              breakdownFilter: {
                                                  // use the event level country code rather than person, to work better with personless users
                                                  breakdown: '$geoip_country_code',
                                                  breakdown_type: 'event',
                                              },
                                              dateRange,
                                              series: [
                                                  {
                                                      event: '$pageview',
                                                      name: 'Pageview',
                                                      kind: NodeKind.EventsNode,
                                                      math: BaseMathType.UniqueUsers,
                                                  },
                                              ],
                                              trendsFilter: {
                                                  display: ChartDisplayType.WorldMap,
                                              },
                                              conversionGoal: featureFlags[
                                                  FEATURE_FLAGS.WEB_ANALYTICS_CONVERSION_GOAL_FILTERS
                                              ]
                                                  ? conversionGoal
                                                  : undefined,
                                              filterTestAccounts,
                                              properties: webAnalyticsFilters,
                                          },
                                          hidePersonsModal: true,
                                          embedded: true,
                                      },
                                      insightProps: createInsightProps(TileId.GEOGRAPHY, GeographyTab.MAP),
                                      canOpenInsight: true,
                                  },
                                  createTableTab(
                                      TileId.GEOGRAPHY,
                                      GeographyTab.COUNTRIES,
                                      'Countries',
                                      'Countries',
                                      WebStatsBreakdown.Country
                                  ),
                                  createTableTab(
                                      TileId.GEOGRAPHY,
                                      GeographyTab.REGIONS,
                                      'Regions',
                                      'Regions',
                                      WebStatsBreakdown.Region
                                  ),
                                  createTableTab(
                                      TileId.GEOGRAPHY,
                                      GeographyTab.CITIES,
                                      'Cities',
                                      'Cities',
                                      WebStatsBreakdown.City
                                  ),
                                  createTableTab(
                                      TileId.GEOGRAPHY,
                                      GeographyTab.TIMEZONES,
                                      'Timezones',
                                      'Timezones',
                                      WebStatsBreakdown.Timezone
                                  ),
                                  createTableTab(
                                      TileId.GEOGRAPHY,
                                      GeographyTab.LANGUAGES,
                                      'Languages',
                                      'Languages',
                                      WebStatsBreakdown.Language
                                  ),
                              ],
                          }
                        : null,
                    !conversionGoal
                        ? {
                              kind: 'query',
                              tileId: TileId.RETENTION,
                              title: 'Retention',
                              layout: {
                                  colSpanClassName: 'md:col-span-2',
                              },
                              query: {
                                  kind: NodeKind.InsightVizNode,
                                  source: {
                                      kind: NodeKind.RetentionQuery,
                                      properties: webAnalyticsFilters,
                                      dateRange,
                                      filterTestAccounts,
                                      retentionFilter: {
                                          retentionType: RETENTION_FIRST_TIME,
                                          retentionReference: 'total',
                                          totalIntervals: isGreaterThanMd ? 8 : 5,
                                          period: RetentionPeriod.Week,
                                      },
                                  },
                                  vizSpecificOptions: {
                                      [InsightType.RETENTION]: {
                                          hideLineGraph: true,
                                          hideSizeColumn: !isGreaterThanMd,
                                          useSmallLayout: !isGreaterThanMd,
                                      },
                                  },
                                  embedded: true,
                              },
                              insightProps: createInsightProps(TileId.RETENTION),
                              canOpenInsight: false,
                              canOpenModal: true,
                              docs: {
                                  url: 'https://posthog.com/docs/web-analytics/dashboard#retention',
                                  title: 'Retention',
                                  description: (
                                      <>
                                          <div>
                                              <p>
                                                  Retention creates a cohort of unique users who performed any event for
                                                  the first time in the last week. It then tracks the percentage of
                                                  users who return to perform any event in the following weeks.
                                              </p>
                                              <p>
                                                  You want the numbers numbers to be the highest possible, suggesting
                                                  that people that come to your page continue coming to your page - and
                                                  performing an actions. Also, the further down the table the higher the
                                                  numbers should be (or at least as high), which would indicate that
                                                  you're either increasing or keeping your retention at the same level.
                                              </p>
                                          </div>
                                      </>
                                  ),
                              },
                          }
                        : null,
                    // Hiding if conversionGoal is set already because values aren't representative
                    !conversionGoal && featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_CONVERSION_GOALS]
                        ? {
                              kind: 'query',
                              tileId: TileId.GOALS,
                              title: 'Goals',
                              layout: {
                                  colSpanClassName: 'md:col-span-2',
                              },
                              query: {
                                  full: true,
                                  kind: NodeKind.DataTableNode,
                                  source: {
                                      kind: NodeKind.WebGoalsQuery,
                                      properties: webAnalyticsFilters,
                                      dateRange,
                                      compareFilter,
                                      sampling,
                                      limit: 10,
                                      filterTestAccounts,
                                  },
                                  embedded: true,
                                  columns: ['breakdown_value', 'visitors', 'views'],
                              },
                              insightProps: createInsightProps(TileId.GOALS),
                              canOpenInsight: false,
                              canOpenModal: false,
                              docs: {
                                  url: 'https://posthog.com/docs/web-analytics/dashboard#goals',
                                  title: 'Goals',
                                  description: (
                                      <>
                                          <div>
                                              <p>
                                                  Goals shows your pinned or most recently created actions and the
                                                  number of conversions they've had. You can set a custom event or
                                                  action as a{' '}
                                                  <Link to="https://posthog.com/docs/web-analytics/conversion-goals">
                                                      conversion goal
                                                  </Link>{' '}
                                                  at the top of the dashboard for more specific metrics.
                                              </p>
                                          </div>
                                      </>
                                  ),
                              },
                          }
                        : null,
                    !conversionGoal && featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_REPLAY]
                        ? {
                              kind: 'replay',
                              tileId: TileId.REPLAY,
                              layout: {
                                  colSpanClassName: conversionGoal ? 'md:col-span-full' : 'md:col-span-1',
                              },
                              docs: {
                                  url: 'https://posthog.com/docs/session-replay',
                                  title: 'Session Replay',
                                  description:
                                      'Play back sessions to diagnose UI issues, improve support, and get context for nuanced user behavior.',
                              },
                          }
                        : null,
                    !conversionGoal && featureFlags[FEATURE_FLAGS.ERROR_TRACKING]
                        ? {
                              kind: 'error_tracking',
                              tileId: TileId.ERROR_TRACKING,
                              layout: {
                                  colSpanClassName: 'md:col-span-1',
                              },
                              query: errorTrackingQuery({
                                  orderBy: 'users',
                                  dateRange: dateRange,
                                  filterTestAccounts: filterTestAccounts,
                                  filterGroup: replayFilters.filter_group,
                                  sparklineSelectedPeriod: null,
                                  columns: ['error', 'users', 'occurrences'],
                                  limit: 4,
                              }),
                              docs: {
                                  url: 'https://posthog.com/docs/error-tracking',
                                  title: 'Error Tracking',
                                  description: (
                                      <>
                                          <div>
                                              <p>
                                                  Error tracking allows you to track, investigate, and resolve
                                                  exceptions your customers face.
                                              </p>
                                              <p>
                                                  Errors are captured as <code>$exception</code> events which means that
                                                  you can create insights, filter recordings and trigger surveys based
                                                  on them exactly the same way you can for any other type of event.
                                              </p>
                                          </div>
                                      </>
                                  ),
                              },
                          }
                        : null,
                ]
                return allTiles.filter(isNotNil)
            },
        ],
        modal: [
            (s) => [s.tiles, s._modalTileAndTab],
            (tiles, modalTileAndTab): WebDashboardModalQuery | null => {
                if (!modalTileAndTab) {
                    return null
                }
                const { tileId, tabId } = modalTileAndTab
                const tile = tiles.find((tile) => tile.tileId === tileId)
                if (!tile) {
                    return null
                }

                const extendQuery = (query: QuerySchema): QuerySchema => {
                    if (
                        query.kind === NodeKind.DataTableNode &&
                        (query.source.kind === NodeKind.WebStatsTableQuery ||
                            query.source.kind === NodeKind.WebExternalClicksTableQuery ||
                            query.source.kind === NodeKind.WebGoalsQuery)
                    ) {
                        return {
                            ...query,
                            source: {
                                ...query.source,
                                limit: 50,
                            },
                        }
                    }
                    return query
                }

                if (tile.kind === 'tabs') {
                    const tab = tile.tabs.find((tab) => tab.id === tabId)
                    if (!tab) {
                        return null
                    }
                    return {
                        tileId,
                        tabId,
                        title: tab.title,
                        showIntervalSelect: tab.showIntervalSelect,
                        showPathCleaningControls: tab.showPathCleaningControls,
                        insightProps: {
                            dashboardItemId: getDashboardItemId(tileId, tabId, true),
                            loadPriority: 0,
                            doNotLoad: false,
                            dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
                        },
                        query: extendQuery(tab.query),
                        canOpenInsight: tab.canOpenInsight,
                    }
                } else if (tile.kind === 'query') {
                    return {
                        tileId,
                        title: tile.title,
                        showIntervalSelect: tile.showIntervalSelect,
                        showPathCleaningControls: tile.showPathCleaningControls,
                        insightProps: {
                            dashboardItemId: getDashboardItemId(tileId, undefined, true),
                            loadPriority: 0,
                            dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
                        },
                        query: extendQuery(tile.query),
                    }
                }
                return null
            },
        ],
        hasCountryFilter: [
            (s) => [s.webAnalyticsFilters],
            (webAnalyticsFilters: WebAnalyticsPropertyFilters) => {
                return webAnalyticsFilters.some((filter) => filter.key === '$geoip_country_code')
            },
        ],
        hasDeviceTypeFilter: [
            (s) => [s.webAnalyticsFilters],
            (webAnalyticsFilters: WebAnalyticsPropertyFilters) => {
                return webAnalyticsFilters.some((filter) => filter.key === '$device_type')
            },
        ],
        hasBrowserFilter: [
            (s) => [s.webAnalyticsFilters],
            (webAnalyticsFilters: WebAnalyticsPropertyFilters) => {
                return webAnalyticsFilters.some((filter) => filter.key === '$browser')
            },
        ],
        hasOSFilter: [
            (s) => [s.webAnalyticsFilters],
            (webAnalyticsFilters: WebAnalyticsPropertyFilters) => {
                return webAnalyticsFilters.some((filter) => filter.key === '$os')
            },
        ],
        replayFilters: [
            (s) => [s.webAnalyticsFilters, s.dateFilter, s.shouldFilterTestAccounts, s.conversionGoal, s.featureFlags],
            (
                webAnalyticsFilters: WebAnalyticsPropertyFilters,
                dateFilter,
                shouldFilterTestAccounts,
                conversionGoal,
                featureFlags
            ): RecordingUniversalFilters => {
                const filters: UniversalFiltersGroupValue[] = [...webAnalyticsFilters]
                if (conversionGoal && featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_CONVERSION_GOAL_FILTERS]) {
                    if ('actionId' in conversionGoal) {
                        filters.push({
                            id: conversionGoal.actionId,
                            name: String(conversionGoal.actionId),
                            type: 'actions',
                        })
                    } else if ('customEventName' in conversionGoal) {
                        filters.push({
                            id: conversionGoal.customEventName,
                            name: conversionGoal.customEventName,
                            type: 'events',
                        })
                    }
                }

                return {
                    filter_test_accounts: shouldFilterTestAccounts,

                    date_from: dateFilter.dateFrom,
                    date_to: dateFilter.dateTo,
                    filter_group: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: filters,
                            },
                        ],
                    },
                    duration: [
                        {
                            type: PropertyFilterType.Recording,
                            key: 'active_seconds',
                            operator: PropertyOperator.GreaterThan,
                            value: 1,
                        },
                    ],
                }
            },
        ],
        getNewInsightUrl: [
            (s) => [s.tiles],
            (tiles) => {
                return function getNewInsightUrl(tileId: TileId, tabId?: string): string | undefined {
                    const formatQueryForNewInsight = (query: QuerySchema): QuerySchema => {
                        if (query.kind === NodeKind.InsightVizNode) {
                            return {
                                ...query,
                                embedded: undefined,
                                hidePersonsModal: undefined,
                            }
                        }
                        return query
                    }

                    const tile = tiles.find((tile) => tile.tileId === tileId)
                    if (!tile) {
                        return undefined
                    }
                    if (tile.kind === 'tabs') {
                        const tab = tile.tabs.find((tab) => tab.id === tabId)
                        if (!tab) {
                            return undefined
                        }
                        return urls.insightNew(undefined, undefined, formatQueryForNewInsight(tab.query))
                    } else if (tile.kind === 'query') {
                        return urls.insightNew(undefined, undefined, formatQueryForNewInsight(tile.query))
                    } else if (tile.kind === 'replay') {
                        return urls.replay()
                    }
                }
            },
        ],
    })),
    loaders(() => ({
        // load the status check query here and pass the response into the component, so the response
        // is accessible in this logic
        statusCheck: {
            __default: null as WebAnalyticsStatusCheck | null,
            loadStatusCheck: async (): Promise<WebAnalyticsStatusCheck> => {
                const [pageviewResult, pageleaveResult, pageleaveScroll] = await Promise.allSettled([
                    api.eventDefinitions.list({
                        event_type: EventDefinitionType.Event,
                        search: '$pageview',
                    }),
                    api.eventDefinitions.list({
                        event_type: EventDefinitionType.Event,
                        search: '$pageleave',
                    }),
                    api.propertyDefinitions.list({
                        event_names: ['$pageleave'],
                        properties: ['$prev_pageview_max_content_percentage'],
                    }),
                ])

                // no need to worry about pagination here, event names beginning with $ are reserved, and we're not
                // going to add enough reserved event names that match this search term to cause problems
                const pageviewEntry =
                    pageviewResult.status === 'fulfilled'
                        ? pageviewResult.value.results.find((r) => r.name === '$pageview')
                        : undefined

                const pageleaveEntry =
                    pageleaveResult.status === 'fulfilled'
                        ? pageleaveResult.value.results.find((r) => r.name === '$pageleave')
                        : undefined

                const pageleaveScrollEntry =
                    pageleaveScroll.status === 'fulfilled'
                        ? pageleaveScroll.value.results.find((r) => r.name === '$prev_pageview_max_content_percentage')
                        : undefined

                const isSendingPageViews = !!pageviewEntry && !isDefinitionStale(pageviewEntry)
                const isSendingPageLeaves = !!pageleaveEntry && !isDefinitionStale(pageleaveEntry)
                const isSendingPageLeavesScroll = !!pageleaveScrollEntry && !isDefinitionStale(pageleaveScrollEntry)

                return {
                    isSendingPageViews,
                    isSendingPageLeaves,
                    isSendingPageLeavesScroll,
                }
            },
        },
        shouldShowGeographyTile: {
            _default: null as boolean | null,
            loadShouldShowGeographyTile: async (): Promise<boolean> => {
                const [propertiesResponse, pluginsResponse, pluginsConfigResponse] = await Promise.allSettled([
                    api.propertyDefinitions.list({
                        event_names: ['$pageview'],
                        properties: ['$geoip_country_code'],
                    }),
                    api.loadPaginatedResults<PluginType>('api/organizations/@current/plugins'),
                    api.loadPaginatedResults<PluginConfigTypeNew>('api/plugin_config'),
                ])

                const hasNonStaleCountryCodeDefinition =
                    propertiesResponse.status === 'fulfilled' &&
                    propertiesResponse.value.results.some(
                        (property) => property.name === '$geoip_country_code' && !isDefinitionStale(property)
                    )

                if (!hasNonStaleCountryCodeDefinition) {
                    return false
                }

                const geoIpPlugin =
                    pluginsResponse.status === 'fulfilled' &&
                    pluginsResponse.value.find((plugin) => plugin.url && GEOIP_PLUGIN_URLS.includes(plugin.url))
                const geoIpPluginId = geoIpPlugin ? geoIpPlugin.id : undefined

                const geoIpPluginConfig =
                    isNotNil(geoIpPluginId) &&
                    pluginsConfigResponse.status === 'fulfilled' &&
                    pluginsConfigResponse.value.find((plugin) => plugin.plugin === geoIpPluginId)

                return !!geoIpPluginConfig && geoIpPluginConfig.enabled
            },
        },
    })),

    // start the loaders after mounting the logic
    afterMount(({ actions }) => {
        actions.loadStatusCheck()
        actions.loadShouldShowGeographyTile()
    }),
    windowValues({
        isGreaterThanMd: (window: Window) => window.innerWidth > 768,
    }),

    actionToUrl(({ values }) => {
        const stateToUrl = (): string => {
            const {
                webAnalyticsFilters,
                conversionGoal,
                dateFilter: { dateTo, dateFrom, interval },
                _sourceTab,
                _deviceTab,
                _pathTab,
                _geographyTab,
                _graphsTab,
                isPathCleaningEnabled,
                shouldFilterTestAccounts,
                compareFilter,
            } = values

            const urlParams = new URLSearchParams()
            if (webAnalyticsFilters.length > 0) {
                urlParams.set('filters', JSON.stringify(webAnalyticsFilters))
            }
            if (conversionGoal) {
                if ('actionId' in conversionGoal) {
                    urlParams.set('conversionGoal.actionId', conversionGoal.actionId.toString())
                } else {
                    urlParams.set('conversionGoal.customEventName', conversionGoal.customEventName)
                }
            }
            if (dateFrom !== initialDateFrom || dateTo !== initialDateTo || interval !== initialInterval) {
                urlParams.set('date_from', dateFrom ?? '')
                urlParams.set('date_to', dateTo ?? '')
                urlParams.set('interval', interval ?? '')
            }
            if (_deviceTab) {
                urlParams.set('device_tab', _deviceTab)
            }
            if (_sourceTab) {
                urlParams.set('source_tab', _sourceTab)
            }
            if (_graphsTab) {
                urlParams.set('graphs_tab', _graphsTab)
            }
            if (_pathTab) {
                urlParams.set('path_tab', _pathTab)
            }
            if (_geographyTab) {
                urlParams.set('geography_tab', _geographyTab)
            }
            if (isPathCleaningEnabled != null) {
                urlParams.set('path_cleaning', isPathCleaningEnabled.toString())
            }
            if (shouldFilterTestAccounts != null) {
                urlParams.set('filter_test_accounts', shouldFilterTestAccounts.toString())
            }
            if (compareFilter) {
                urlParams.set('compare_filter', JSON.stringify(compareFilter))
            }
            return `/web?${urlParams.toString()}`
        }

        return {
            setWebAnalyticsFilters: stateToUrl,
            togglePropertyFilter: stateToUrl,
            setConversionGoal: stateToUrl,
            setDates: stateToUrl,
            setInterval: stateToUrl,
            setDeviceTab: stateToUrl,
            setSourceTab: stateToUrl,
            setGraphsTab: stateToUrl,
            setPathTab: stateToUrl,
            setGeographyTab: stateToUrl,
            setCompareFilter: stateToUrl,
        }
    }),

    urlToAction(({ actions, values }) => ({
        '/web': (
            _,
            {
                filters,
                'conversionGoal.actionId': conversionGoalActionId,
                'conversionGoal.customEventName': conversionGoalCustomEventName,
                date_from,
                date_to,
                interval,
                device_tab,
                source_tab,
                graphs_tab,
                path_tab,
                geography_tab,
                path_cleaning,
                filter_test_accounts,
                compare_filter,
            }
        ) => {
            const parsedFilters = isWebAnalyticsPropertyFilters(filters) ? filters : undefined

            if (parsedFilters && !objectsEqual(parsedFilters, values.webAnalyticsFilters)) {
                actions.setWebAnalyticsFilters(parsedFilters)
            }
            if (
                conversionGoalActionId &&
                conversionGoalActionId !== (values.conversionGoal as ActionConversionGoal)?.actionId
            ) {
                actions.setConversionGoal({ actionId: parseInt(conversionGoalActionId, 10) })
            } else if (
                conversionGoalCustomEventName &&
                conversionGoalCustomEventName !== (values.conversionGoal as CustomEventConversionGoal)?.customEventName
            ) {
                actions.setConversionGoal({ customEventName: conversionGoalCustomEventName })
            }
            if (
                (date_from && date_from !== values.dateFilter.dateFrom) ||
                (date_to && date_to !== values.dateFilter.dateTo) ||
                (interval && interval !== values.dateFilter.interval)
            ) {
                actions.setDatesAndInterval(date_from, date_to, interval)
            }
            if (device_tab && device_tab !== values._deviceTab) {
                actions.setDeviceTab(device_tab)
            }
            if (source_tab && source_tab !== values._sourceTab) {
                actions.setSourceTab(source_tab)
            }
            if (graphs_tab && graphs_tab !== values._graphsTab) {
                actions.setGraphsTab(graphs_tab)
            }
            if (path_tab && path_tab !== values._pathTab) {
                actions.setPathTab(path_tab)
            }
            if (geography_tab && geography_tab !== values._geographyTab) {
                actions.setGeographyTab(geography_tab)
            }
            if (path_cleaning && path_cleaning !== values.isPathCleaningEnabled) {
                actions.setIsPathCleaningEnabled([true, 'true', 1, '1'].includes(path_cleaning))
            }
            if (filter_test_accounts && filter_test_accounts !== values.shouldFilterTestAccounts) {
                actions.setShouldFilterTestAccounts([true, 'true', 1, '1'].includes(filter_test_accounts))
            }
            if (compare_filter && !objectsEqual(compare_filter, values.compareFilter)) {
                actions.setCompareFilter(compare_filter)
            }
        },
    })),
    listeners(({ values, actions }) => {
        const checkGraphsTabIsCompatibleWithConversionGoal = (
            tab: string,
            conversionGoal: WebAnalyticsConversionGoal | null
        ): void => {
            if (conversionGoal) {
                if (tab === GraphsTab.PAGE_VIEWS || tab === GraphsTab.NUM_SESSION) {
                    actions.setGraphsTab(GraphsTab.UNIQUE_USERS)
                }
            } else {
                if (
                    tab === GraphsTab.TOTAL_CONVERSIONS ||
                    tab === GraphsTab.CONVERSION_RATE ||
                    tab === GraphsTab.UNIQUE_CONVERSIONS
                ) {
                    actions.setGraphsTab(GraphsTab.UNIQUE_USERS)
                }
            }
        }

        return {
            setGraphsTab: ({ tab }) => {
                checkGraphsTabIsCompatibleWithConversionGoal(tab, values.conversionGoal)
            },
            setConversionGoal: [
                ({ conversionGoal }) => {
                    checkGraphsTabIsCompatibleWithConversionGoal(values.graphsTab, conversionGoal)
                },
                ({ conversionGoal }, breakpoint) =>
                    checkCustomEventConversionGoalHasSessionIdsHelper(
                        conversionGoal,
                        breakpoint,
                        actions.setConversionGoalWarning,
                        values.featureFlags
                    ),
            ],
        }
    }),
    afterMount(({ actions, values }) => {
        checkCustomEventConversionGoalHasSessionIdsHelper(
            values.conversionGoal,
            undefined,
            actions.setConversionGoalWarning,
            values.featureFlags
        ).catch(() => {
            // ignore, this warning is just a nice-to-have, no point showing an error to the user
        })
    }),
])

const isDefinitionStale = (definition: EventDefinition | PropertyDefinition): boolean => {
    const parsedLastSeen = definition.last_seen_at ? dayjs(definition.last_seen_at) : null
    return !!parsedLastSeen && dayjs().diff(parsedLastSeen, 'seconds') > STALE_EVENT_SECONDS
}

const checkCustomEventConversionGoalHasSessionIdsHelper = async (
    conversionGoal: WebAnalyticsConversionGoal | null,
    breakpoint: BreakPointFunction | undefined,
    setConversionGoalWarning: (warning: ConversionGoalWarning | null) => void,
    featureFlags: FeatureFlagsSet
): Promise<void> => {
    if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_WARN_CUSTOM_EVENT_NO_SESSION]) {
        return
    }

    if (!conversionGoal || !('customEventName' in conversionGoal) || !conversionGoal.customEventName) {
        setConversionGoalWarning(null)
        return
    }
    const { customEventName } = conversionGoal
    // check if we have any conversion events from the last week without sessions ids

    const response = await hogqlQuery(
        `select count() from events where timestamp >= (now() - toIntervalHour(24)) AND ($session_id IS NULL OR $session_id = '') AND event = {event}`,
        { event: customEventName }
    )
    breakpoint?.()
    const row = response.results[0]
    if (row[0]) {
        setConversionGoalWarning(ConversionGoalWarning.CustomEventWithNoSessionId)
    } else {
        setConversionGoalWarning(null)
    }
}
