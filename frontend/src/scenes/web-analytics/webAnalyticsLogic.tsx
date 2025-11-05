import { BreakPointFunction, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { windowValues } from 'kea-window-values'
import posthog from 'posthog-js'

import { IconGear } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'
import { errorTrackingQuery } from '@posthog/products-error-tracking/frontend/queries'

import api from 'lib/api'
import { AuthorizedUrlListType, authorizedUrlListLogic } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { FEATURE_FLAGS, RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Link } from 'lib/lemon-ui/Link/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import {
    UnexpectedNeverError,
    getDefaultInterval,
    isNotNil,
    isValidRelativeOrAbsoluteDate,
    objectsEqual,
    updateDatesWithInterval,
} from 'lib/utils'
import { isDefinitionStale } from 'lib/utils/definitions'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { WEB_VITALS_COLORS, WEB_VITALS_THRESHOLDS } from '~/queries/nodes/WebVitals/definitions'
import { hogqlQuery } from '~/queries/query'
import { isCompareFilter, isWebAnalyticsPropertyFilters } from '~/queries/schema-guards'
import {
    ActionConversionGoal,
    ActionsNode,
    AnyEntityNode,
    CompareFilter,
    CustomEventConversionGoal,
    DataTableNode,
    EventsNode,
    InsightVizNode,
    NodeKind,
    TrendsFilter,
    TrendsQuery,
    WebAnalyticsConversionGoal,
    WebAnalyticsOrderBy,
    WebAnalyticsOrderByDirection,
    WebAnalyticsOrderByFields,
    WebAnalyticsPropertyFilter,
    WebAnalyticsPropertyFilters,
    WebStatsBreakdown,
    WebStatsPathExtractionMethod,
    WebStatsTableQuery,
    WebVitalsMetric,
} from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import {
    AvailableFeature,
    BaseMathType,
    Breadcrumb,
    ChartDisplayType,
    EventDefinitionType,
    FilterLogicalOperator,
    InsightLogicProps,
    InsightType,
    IntervalType,
    PropertyFilterBaseValue,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
    RecordingUniversalFilters,
    RetentionPeriod,
    TeamPublicType,
    TeamType,
    UniversalFiltersGroupValue,
} from '~/types'

import {
    ActiveHoursTab,
    ConversionGoalWarning,
    DeviceTab,
    DeviceType,
    GEOIP_TEMPLATE_IDS,
    GeographyTab,
    GraphsTab,
    INITIAL_DATE_FROM,
    INITIAL_DATE_TO,
    INITIAL_INTERVAL,
    INITIAL_WEB_ANALYTICS_FILTER,
    PathTab,
    ProductTab,
    SourceTab,
    TILES_ALLOWED_ON_PRE_AGGREGATED,
    TabsTileTab,
    TileId,
    TileVisualizationOption,
    WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
    WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
    WebAnalyticsStatusCheck,
    WebAnalyticsTile,
    WebVitalsPercentile,
    eventPropertiesToPathClean,
    getWebAnalyticsBreakdownFilter,
    loadPriorityMap,
    personPropertiesToPathClean,
    sessionPropertiesToPathClean,
} from './common'
import { getDashboardItemId, getNewInsightUrlFactory } from './insightsUtils'
import { marketingAnalyticsTilesLogic } from './tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'
import type { webAnalyticsLogicType } from './webAnalyticsLogicType'

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
const persistConfig = { persist: true, prefix: `${teamId}__` }
export const webAnalyticsLogic = kea<webAnalyticsLogicType>([
    path(['scenes', 'webAnalytics', 'webAnalyticsSceneLogic']),
    connect(() => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            teamLogic,
            ['currentTeam', 'baseCurrency'],
            userLogic,
            ['hasAvailableFeature'],
            preflightLogic,
            ['isDev'],
            authorizedUrlListLogic({ type: AuthorizedUrlListType.WEB_ANALYTICS, actionId: null, experimentId: null }),
            ['authorizedUrls'],
            marketingAnalyticsTilesLogic,
            ['tiles as marketingTiles'],
        ],
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
                activeHoursTab?: string
            }
        ) => ({ type, key, value, tabChange }),
        setGraphsTab: (tab: string) => ({ tab }),
        setSourceTab: (tab: string) => ({ tab }),
        setDeviceTab: (tab: string) => ({ tab }),
        setPathTab: (tab: string) => ({ tab }),
        setGeographyTab: (tab: string) => ({ tab }),
        setActiveHoursTab: (tab: string) => ({ tab }),
        setDomainFilter: (domain: string | null) => ({ domain }),
        setDeviceTypeFilter: (deviceType: DeviceType | null) => ({ deviceType }),
        clearTablesOrderBy: () => true,
        setTablesOrderBy: (orderBy: WebAnalyticsOrderByFields, direction: WebAnalyticsOrderByDirection) => ({
            orderBy,
            direction,
        }),
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setInterval: (interval: IntervalType) => ({ interval }),
        setDatesAndInterval: (dateFrom: string | null, dateTo: string | null, interval: IntervalType) => ({
            dateFrom,
            dateTo,
            interval,
        }),
        setIsPathCleaningEnabled: (isPathCleaningEnabled: boolean) => ({ isPathCleaningEnabled }),
        setPathExtractionMethod: (pathExtractionMethod: WebStatsPathExtractionMethod) => ({ pathExtractionMethod }),
        setShouldFilterTestAccounts: (shouldFilterTestAccounts: boolean) => ({ shouldFilterTestAccounts }),
        setShouldStripQueryParams: (shouldStripQueryParams: boolean) => ({ shouldStripQueryParams }),
        setConversionGoal: (conversionGoal: WebAnalyticsConversionGoal | null) => ({ conversionGoal }),
        openAsNewInsight: (tileId: TileId, tabId?: string) => ({ tileId, tabId }),
        setConversionGoalWarning: (warning: ConversionGoalWarning | null) => ({ warning }),
        setCompareFilter: (compareFilter: CompareFilter) => ({ compareFilter }),
        setProductTab: (tab: ProductTab) => ({ tab }),
        setWebVitalsPercentile: (percentile: WebVitalsPercentile) => ({ percentile }),
        setWebVitalsTab: (tab: WebVitalsMetric) => ({ tab }),
        setTileVisualization: (tileId: TileId, visualization: TileVisualizationOption) => ({ tileId, visualization }),
        setTileVisibility: (tileId: TileId, visible: boolean) => ({ tileId, visible }),
        resetTileVisibility: () => true,
    }),
    loaders(({ values }) => ({
        // load the status check query here and pass the response into the component, so the response
        // is accessible in this logic
        statusCheck: {
            __default: null as WebAnalyticsStatusCheck | null,
            loadStatusCheck: async (): Promise<WebAnalyticsStatusCheck> => {
                const [webVitalsResult, pageviewResult, pageleaveResult, pageleaveScroll] = await Promise.allSettled([
                    api.eventDefinitions.list({
                        event_type: EventDefinitionType.Event,
                        search: '$web_vitals',
                    }),
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
                const webVitalsEntry =
                    webVitalsResult.status === 'fulfilled'
                        ? webVitalsResult.value.results.find((r) => r.name === '$web_vitals')
                        : undefined

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

                const isSendingWebVitals = !!webVitalsEntry && !isDefinitionStale(webVitalsEntry)
                const isSendingPageViews = !!pageviewEntry && !isDefinitionStale(pageviewEntry)
                const isSendingPageLeaves = !!pageleaveEntry && !isDefinitionStale(pageleaveEntry)
                const isSendingPageLeavesScroll = !!pageleaveScrollEntry && !isDefinitionStale(pageleaveScrollEntry)

                return {
                    isSendingWebVitals,
                    isSendingPageViews,
                    isSendingPageLeaves,
                    isSendingPageLeavesScroll,
                    hasAuthorizedUrls: !!values.currentTeam?.app_urls && values.currentTeam.app_urls.length > 0,
                }
            },
        },
        shouldShowGeoIPQueries: {
            _default: null as boolean | null,
            loadShouldShowGeoIPQueries: async (): Promise<boolean> => {
                // Always display on dev mode, we don't always have events and/or hogQL functions
                // but we want the map to be there for debugging purposes
                if (values.isDev) {
                    return true
                }

                const [propertiesResponse, hogFunctionsResponse] = await Promise.allSettled([
                    api.propertyDefinitions.list({
                        event_names: ['$pageview'],
                        properties: ['$geoip_country_code'],
                    }),
                    api.hogFunctions.list({ types: ['transformation'] }),
                ])

                const hasNonStaleCountryCodeDefinition =
                    propertiesResponse.status === 'fulfilled' &&
                    propertiesResponse.value.results.some(
                        (property) => property.name === '$geoip_country_code' && !isDefinitionStale(property)
                    )

                if (!hasNonStaleCountryCodeDefinition) {
                    return false
                }

                if (hogFunctionsResponse.status !== 'fulfilled') {
                    return false
                }

                const enabledGeoIPHogFunction = hogFunctionsResponse.value.results.find((hogFunction) => {
                    const isFromTemplate = GEOIP_TEMPLATE_IDS.includes(hogFunction.template?.id ?? '')
                    const matchesName = hogFunction.name === 'GeoIP' // Failsafe in case someone implements their custom GeoIP function

                    return (isFromTemplate || matchesName) && hogFunction.enabled
                })

                return Boolean(enabledGeoIPHogFunction)
            },
        },
    })),
    reducers({
        rawWebAnalyticsFilters: [
            INITIAL_WEB_ANALYTICS_FILTER,
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
                setDomainFilter: (state) => {
                    // the domain and host filters don't interact well, so remove the host filter when the domain filter is set
                    return state.filter((filter) => filter.key !== '$host')
                },
            },
        ],
        domainFilter: [
            null as string | null,
            persistConfig,
            {
                setDomainFilter: (_: string | null, payload: { domain: string | null }) => {
                    const { domain } = payload
                    return domain
                },
                togglePropertyFilter: (state, { key }) => {
                    // the domain and host filters don't interact well, so remove the domain filter when the host filter is set
                    return key === '$host' ? null : state
                },
                setWebAnalyticsFilters: (state, { webAnalyticsFilters }) => {
                    // the domain and host filters don't interact well, so remove the domain filter when the host filter is set
                    if (webAnalyticsFilters.some((f) => f.key === '$host')) {
                        return null
                    }
                    return state
                },
            },
        ],
        deviceTypeFilter: [
            null as DeviceType | null,
            persistConfig,
            {
                setDeviceTypeFilter: (_: DeviceType | null, payload: unknown) => {
                    const { deviceType } = payload as { deviceType: DeviceType | null }
                    return deviceType
                },
            },
        ],
        _graphsTab: [
            null as string | null,
            persistConfig,
            {
                setGraphsTab: (_, { tab }) => tab,
                togglePropertyFilter: (oldTab, { tabChange }) => tabChange?.graphsTab || oldTab,
                setConversionGoal: (oldTab, { conversionGoal }) => {
                    if (conversionGoal) {
                        return GraphsTab.UNIQUE_CONVERSIONS
                    }
                    return oldTab
                },
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
        _activeHoursTab: [
            null as string | null,
            persistConfig,
            {
                setActiveHoursTab: (_, { tab }) => tab,
            },
        ],
        _isPathCleaningEnabled: [
            true as boolean,
            persistConfig,
            {
                setIsPathCleaningEnabled: (_, { isPathCleaningEnabled }) => isPathCleaningEnabled,
            },
        ],
        pathExtractionMethod: [
            WebStatsPathExtractionMethod.Path as WebStatsPathExtractionMethod,
            persistConfig,
            {
                setPathExtractionMethod: (_, { pathExtractionMethod }) => pathExtractionMethod,
            },
        ],
        tablesOrderBy: [
            null as WebAnalyticsOrderBy | null,
            persistConfig,
            {
                setTablesOrderBy: (_, { orderBy, direction }) => [orderBy, direction],
                clearTablesOrderBy: () => null,

                // Reset the order by when the conversion goal changes because most of the columns are different
                setConversionGoal: () => null,
            },
        ],
        dateFilter: [
            {
                dateFrom: INITIAL_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
                interval: INITIAL_INTERVAL,
            },
            persistConfig,
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
                        dateFrom,
                        interval: getDefaultInterval(dateFrom, dateTo),
                    }
                },
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
        productTab: [
            ProductTab.ANALYTICS as ProductTab,
            {
                setProductTab: (_, { tab }) => tab,
            },
        ],
        webVitalsPercentile: [
            PropertyMathType.P90 as WebVitalsPercentile,
            persistConfig,
            {
                setWebVitalsPercentile: (_, { percentile }) => percentile,
            },
        ],
        webVitalsTab: [
            'INP' as WebVitalsMetric,
            {
                setWebVitalsTab: (_, { tab }) => tab,
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
        hiddenTiles: [
            [] as TileId[],
            persistConfig,
            {
                setTileVisibility: (state, { tileId, visible }) => {
                    if (visible) {
                        return state.filter((id) => id !== tileId)
                    }
                    return state.includes(tileId) ? state : [...state, tileId]
                },
                resetTileVisibility: () => [],
            },
        ],
    }),
    windowValues({
        isGreaterThanMd: (window: Window) => window.innerWidth > 768,
    }),
    selectors({
        preAggregatedEnabled: [
            (s) => [s.featureFlags, s.currentTeam],
            (featureFlags: Record<string, boolean>, currentTeam: TeamPublicType | TeamType | null) => {
                return (
                    featureFlags[FEATURE_FLAGS.SETTINGS_WEB_ANALYTICS_PRE_AGGREGATED_TABLES] &&
                    currentTeam?.modifiers?.useWebAnalyticsPreAggregatedTables
                )
            },
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        key: Scene.WebAnalytics,
                        name: `Web analytics`,
                        path: urls.webAnalytics(),
                        iconType: 'web_analytics',
                    },
                ]
            },
        ],
        graphsTab: [(s) => [s._graphsTab], (graphsTab: string | null) => graphsTab || GraphsTab.UNIQUE_USERS],
        sourceTab: [(s) => [s._sourceTab], (sourceTab: string | null) => sourceTab || SourceTab.CHANNEL],
        deviceTab: [(s) => [s._deviceTab], (deviceTab: string | null) => deviceTab || DeviceTab.DEVICE_TYPE],
        pathTab: [(s) => [s._pathTab], (pathTab: string | null) => pathTab || PathTab.PATH],
        geographyTab: [(s) => [s._geographyTab], (geographyTab: string | null) => geographyTab || GeographyTab.MAP],
        activeHoursTab: [
            (s) => [s._activeHoursTab],
            (activeHoursTab: string | null) => activeHoursTab || ActiveHoursTab.UNIQUE,
        ],
        isPathCleaningEnabled: [
            (s) => [s._isPathCleaningEnabled, s.hasAvailableFeature],
            (isPathCleaningEnabled: boolean, hasAvailableFeature) => {
                return hasAvailableFeature(AvailableFeature.PATHS_ADVANCED) && isPathCleaningEnabled
            },
        ],
        hasHostFilter: [(s) => [s.rawWebAnalyticsFilters], (filters) => filters.some((f) => f.key === '$host')],
        webAnalyticsFilters: [
            (s) => [s.rawWebAnalyticsFilters, s.isPathCleaningEnabled, s.domainFilter, s.deviceTypeFilter],
            (
                rawWebAnalyticsFilters: WebAnalyticsPropertyFilters,
                isPathCleaningEnabled: boolean,
                domainFilter: string | null,
                deviceTypeFilter: DeviceType | null
            ) => {
                let filters = rawWebAnalyticsFilters

                // Add domain filter if set
                if (domainFilter && domainFilter !== 'all') {
                    // Remove the leading protocol if it exists
                    const value = domainFilter.replace(/^https?:\/\//, '')

                    filters = [
                        ...filters,
                        {
                            key: '$host',
                            value: value,
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ]
                }

                // Add device type filter if set
                if (deviceTypeFilter) {
                    filters = [
                        ...filters,
                        {
                            key: '$device_type',
                            // Extra handling for device type to include mobile+tablet as a single filter
                            value: deviceTypeFilter === 'Desktop' ? 'Desktop' : ['Mobile', 'Tablet'],
                            operator: PropertyOperator.Exact,
                            type: PropertyFilterType.Event,
                        },
                    ]
                }

                // Translate exact path filters to cleaned path filters
                if (isPathCleaningEnabled) {
                    filters = filters.map((filter) => {
                        if (filter.operator !== PropertyOperator.Exact) {
                            return filter
                        }
                        let propertiesToPathClean: Set<string>
                        switch (filter.type) {
                            case PropertyFilterType.Event:
                                propertiesToPathClean = eventPropertiesToPathClean
                                break
                            case PropertyFilterType.Person:
                                propertiesToPathClean = personPropertiesToPathClean
                                break
                            case PropertyFilterType.Session:
                                propertiesToPathClean = sessionPropertiesToPathClean
                                break
                            default:
                                throw new UnexpectedNeverError(filter)
                        }
                        if (propertiesToPathClean.has(filter.key)) {
                            return {
                                ...filter,
                                operator: PropertyOperator.IsCleanedPathExact,
                            }
                        }
                        return filter
                    })
                }

                return filters
            },
        ],
        tabs: [
            (s) => [
                s.graphsTab,
                s.sourceTab,
                s.deviceTab,
                s.pathTab,
                s.geographyTab,
                s.activeHoursTab,
                s.shouldShowGeoIPQueries,
            ],
            (graphsTab, sourceTab, deviceTab, pathTab, geographyTab, activeHoursTab, shouldShowGeoIPQueries) => ({
                graphsTab,
                sourceTab,
                deviceTab,
                pathTab,
                geographyTab,
                activeHoursTab,
                shouldShowGeoIPQueries,
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
            (s) => [
                s.webAnalyticsFilters,
                s.replayFilters,
                s.dateFilter,
                s.compareFilter,
                s.webVitalsTab,
                s.webVitalsPercentile,
                s.tablesOrderBy,
                s.conversionGoal,
            ],
            (
                webAnalyticsFilters,
                replayFilters,
                dateFilter,
                compareFilter,
                webVitalsTab,
                webVitalsPercentile,
                tablesOrderBy,
                conversionGoal
            ) => ({
                webAnalyticsFilters,
                replayFilters,
                dateFilter,
                compareFilter,
                webVitalsTab,
                webVitalsPercentile,
                tablesOrderBy,
                conversionGoal,
            }),
        ],
        replayFilters: [
            (s) => [s.webAnalyticsFilters, s.dateFilter, s.shouldFilterTestAccounts, s.conversionGoal],
            (
                webAnalyticsFilters: WebAnalyticsPropertyFilters,
                dateFilter,
                shouldFilterTestAccounts,
                conversionGoal
            ): RecordingUniversalFilters => {
                const filters: UniversalFiltersGroupValue[] = [...webAnalyticsFilters]
                if (conversionGoal) {
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
        hasCountryFilter: [
            (s) => [s.webAnalyticsFilters],
            (webAnalyticsFilters: WebAnalyticsPropertyFilters) => {
                return webAnalyticsFilters.some((filter) => filter.key === '$geoip_country_code')
            },
        ],
        webVitalsMetricQuery: [
            (s) => [
                s.webVitalsPercentile,
                s.webVitalsTab,
                s.dateFilter,
                s.webAnalyticsFilters,
                s.shouldFilterTestAccounts,
            ],
            (
                webVitalsPercentile,
                webVitalsTab,
                { dateFrom, dateTo, interval },
                webAnalyticsFilters,
                filterTestAccounts
            ): InsightVizNode<TrendsQuery> => ({
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    dateRange: {
                        date_from: dateFrom,
                        date_to: dateTo,
                    },
                    interval,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: '$web_vitals',
                            name: '$web_vitals',
                            custom_name: webVitalsTab,
                            math: webVitalsPercentile,
                            math_property: `$web_vitals_${webVitalsTab}_value`,
                        },
                    ],
                    trendsFilter: {
                        display: ChartDisplayType.ActionsLineGraph,
                        aggregationAxisFormat: webVitalsTab === 'CLS' ? 'numeric' : 'duration_ms',
                        goalLines: [
                            {
                                label: 'Good',
                                value: WEB_VITALS_THRESHOLDS[webVitalsTab].good,
                                displayLabel: false,
                                borderColor: WEB_VITALS_COLORS.good,
                            },
                            {
                                label: 'Poor',
                                value: WEB_VITALS_THRESHOLDS[webVitalsTab].poor,
                                displayLabel: false,
                                borderColor: WEB_VITALS_COLORS.needs_improvements,
                            },
                        ],
                    } as TrendsFilter,
                    filterTestAccounts,
                    properties: webAnalyticsFilters,
                    tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                },
                embedded: false,
            }),
        ],
        authorizedDomains: [
            (s) => [s.authorizedUrls],
            (authorizedUrls) => {
                // There are a couple problems with the raw `authorizedUrls` which we need to fix here:
                // - They are URLs, we want domains
                // - There might be duplicates, so clean them up
                // - There might be duplicates across http/https, so clean them up

                // First create URL objects and group them by hostname+port
                const urlsByDomain = new Map<string, URL[]>()

                for (const urlStr of authorizedUrls) {
                    try {
                        const url = new URL(urlStr)
                        const key = url.host // hostname + port if present
                        if (!urlsByDomain.has(key)) {
                            urlsByDomain.set(key, [])
                        }
                        urlsByDomain.get(key)!.push(url)
                    } catch {
                        // Silently skip URLs that can't be parsed
                    }
                }

                // For each domain, prefer https over http
                return Array.from(urlsByDomain.values()).map((urls) => {
                    const preferredUrl = urls.find((url) => url.protocol === 'https:') ?? urls[0]
                    return preferredUrl.origin
                })
            },
        ],
    }),
    selectors(({ actions }) => ({
        tiles: [
            (s) => [
                s.productTab,
                s.tabs,
                s.controls,
                s.filters,
                s.featureFlags,
                s.isGreaterThanMd,
                s.currentTeam,
                s.tileVisualizations,
                s.preAggregatedEnabled,
                s.marketingTiles,
                s.hiddenTiles,
            ],
            (
                productTab,
                { graphsTab, sourceTab, deviceTab, pathTab, geographyTab, shouldShowGeoIPQueries, activeHoursTab },
                { isPathCleaningEnabled, filterTestAccounts, shouldStripQueryParams },
                {
                    webAnalyticsFilters,
                    replayFilters,
                    dateFilter: { dateFrom, dateTo, interval },
                    conversionGoal,
                    compareFilter,
                    webVitalsPercentile,
                    webVitalsTab,
                    tablesOrderBy,
                },
                featureFlags,
                isGreaterThanMd,
                currentTeam,
                tileVisualizations,
                preAggregatedEnabled,
                marketingTiles,
                hiddenTiles
            ): WebAnalyticsTile[] => {
                const dateRange = { date_from: dateFrom, date_to: dateTo }
                const sampling = { enabled: false, forceSamplingRate: { numerator: 1, denominator: 10 } }

                const uniqueUserSeries: EventsNode = {
                    event: featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_FOR_MOBILE] ? '$screen' : '$pageview',
                    kind: NodeKind.EventsNode,
                    math: BaseMathType.UniqueUsers,
                    name: 'Pageview',
                    custom_name: 'Unique visitors',
                }

                const pageViewsSeries = {
                    ...uniqueUserSeries,
                    math: BaseMathType.TotalCount,
                    custom_name: featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_FOR_MOBILE] ? 'Screen Views' : 'Page views',
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

                // the queries don't currently include revenue when the conversion goal is an action
                const includeRevenue = !(conversionGoal && 'actionId' in conversionGoal)

                const revenueEventsSeries: EventsNode[] =
                    includeRevenue && currentTeam?.revenue_analytics_config
                        ? (currentTeam.revenue_analytics_config.events.map((e) => ({
                              name: e.eventName,
                              event: e.eventName,
                              custom_name: e.eventName,
                              math: PropertyMathType.Sum,
                              kind: NodeKind.EventsNode,
                              math_property: e.revenueProperty,
                              math_property_revenue_currency: e.revenueCurrencyProperty,
                          })) as EventsNode[])
                        : []

                const conversionRevenueSeries =
                    conversionGoal && 'customEventName' in conversionGoal && includeRevenue
                        ? revenueEventsSeries.filter((e) => 'event' in e && e.event === conversionGoal.customEventName)
                        : []

                const createInsightProps = (tile: TileId, tab?: string): InsightLogicProps => {
                    return {
                        dashboardItemId: getDashboardItemId(tile, tab, false),
                        loadPriority: loadPriorityMap[tile],
                        dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
                    }
                }

                const createGraphsTrendsTab = (
                    id: GraphsTab,
                    title: string | JSX.Element,
                    linkText: string | JSX.Element,
                    series: AnyEntityNode[],
                    trendsFilter?: Partial<TrendsFilter>,
                    trendsQueryProperties?: Partial<TrendsQuery>
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
                            conversionGoal,
                            properties: webAnalyticsFilters,
                            tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                            ...trendsQueryProperties,
                        },
                        hidePersonsModal: true,
                        embedded: true,
                        hideTooltipOnScroll: true,
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
                    const columns = [
                        'breakdown_value',
                        'visitors',
                        'views',
                        source?.includeBounceRate ? 'bounce_rate' : null,
                        'cross_sell',
                    ].filter(isNotNil)

                    // Check if this tile has a visualization preference
                    const visualization =
                        tileVisualizations[tileId as unknown as keyof typeof tileVisualizations] || undefined

                    const baseTabProps = {
                        id: tabId,
                        title,
                        linkText,
                        insightProps: createInsightProps(tileId, tabId),
                        canOpenModal: true,
                        ...tab,
                    }

                    // In case of a graph, we need to use the breakdownFilter and a InsightsVizNode,
                    // which will actually be handled by a WebStatsTrendTile instead of a WebStatsTableTile
                    if (visualization === 'graph') {
                        return {
                            ...baseTabProps,
                            query: {
                                kind: NodeKind.InsightVizNode,
                                source: {
                                    kind: NodeKind.TrendsQuery,
                                    dateRange,
                                    interval,
                                    series: [uniqueUserSeries],
                                    trendsFilter: {
                                        display: ChartDisplayType.ActionsLineGraph,
                                    },
                                    breakdownFilter: getWebAnalyticsBreakdownFilter(breakdownBy),
                                    filterTestAccounts,
                                    conversionGoal,
                                    properties: webAnalyticsFilters,
                                    tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                                },
                                hidePersonsModal: true,
                                embedded: true,
                                hideTooltipOnScroll: true,
                            },
                            canOpenInsight: true,
                            canOpenModal: false,
                        }
                    }

                    return {
                        ...baseTabProps,
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
                                conversionGoal,
                                orderBy: tablesOrderBy ?? undefined,
                                tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                                ...source,
                            },
                            embedded: false,
                            showActions: true,
                            columns,
                        },
                    }
                }

                let errorTrackingQ: DataTableNode | undefined

                try {
                    errorTrackingQ = errorTrackingQuery({
                        orderBy: 'users',
                        dateRange: dateRange,
                        filterTestAccounts: filterTestAccounts,
                        filterGroup: replayFilters.filter_group,
                        columns: ['error', 'users', 'occurrences'],
                        limit: 4,
                    })
                } catch (e) {
                    posthog.captureException(e, { dateRange, replayFilters, filterTestAccounts })
                }

                if (productTab === ProductTab.WEB_VITALS) {
                    const createSeries = (name: WebVitalsMetric, math: PropertyMathType): AnyEntityNode => ({
                        kind: NodeKind.EventsNode,
                        event: '$web_vitals',
                        name: '$web_vitals',
                        custom_name: name,
                        math: math,
                        math_property: `$web_vitals_${name}_value`,
                    })

                    return [
                        {
                            kind: 'query',
                            tileId: TileId.WEB_VITALS,
                            layout: {
                                colSpanClassName: 'md:col-span-full',
                                orderWhenLargeClassName: 'xxl:order-0',
                            },
                            query: {
                                kind: NodeKind.WebVitalsQuery,
                                properties: webAnalyticsFilters,
                                source: {
                                    kind: NodeKind.TrendsQuery,
                                    dateRange,
                                    interval,
                                    series: (['INP', 'LCP', 'CLS', 'FCP'] as WebVitalsMetric[]).flatMap((metric) =>
                                        [PropertyMathType.P75, PropertyMathType.P90, PropertyMathType.P99].map((math) =>
                                            createSeries(metric, math)
                                        )
                                    ),
                                    trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
                                    compareFilter,
                                    filterTestAccounts,
                                    properties: webAnalyticsFilters,
                                },
                                tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                            },
                            insightProps: {
                                dashboardItemId: getDashboardItemId(TileId.WEB_VITALS, 'web-vitals-overview', false),
                                loadPriority: loadPriorityMap[TileId.WEB_VITALS],
                                dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
                            },
                            showIntervalSelect: true,
                        },
                        {
                            kind: 'query',
                            tileId: TileId.WEB_VITALS_PATH_BREAKDOWN,
                            layout: {
                                colSpanClassName: 'md:col-span-full',
                                orderWhenLargeClassName: 'xxl:order-0',
                            },
                            query: {
                                kind: NodeKind.WebVitalsPathBreakdownQuery,
                                dateRange,
                                filterTestAccounts,
                                properties: webAnalyticsFilters,
                                percentile: webVitalsPercentile,
                                metric: webVitalsTab,
                                doPathCleaning: isPathCleaningEnabled,
                                pathExtractionMethod,
                                thresholds: [
                                    WEB_VITALS_THRESHOLDS[webVitalsTab].good,
                                    WEB_VITALS_THRESHOLDS[webVitalsTab].poor,
                                ],
                            },
                            insightProps: {
                                dashboardItemId: getDashboardItemId(
                                    TileId.WEB_VITALS_PATH_BREAKDOWN,
                                    'web-vitals-path-breakdown',
                                    false
                                ),
                                loadPriority: loadPriorityMap[TileId.WEB_VITALS_PATH_BREAKDOWN],
                                dataNodeCollectionId: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
                            },
                        },
                    ]
                }

                if (productTab === ProductTab.MARKETING) {
                    return marketingTiles as unknown as WebAnalyticsTile[]
                }

                const allTiles: (WebAnalyticsTile | null)[] = [
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
                            includeRevenue,
                        },
                        insightProps: createInsightProps(TileId.OVERVIEW),
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
                                !conversionGoal && revenueEventsSeries?.length
                                    ? createGraphsTrendsTab(
                                          GraphsTab.REVENUE_EVENTS,
                                          <span>
                                              Revenue&nbsp;<LemonTag type="warning">BETA</LemonTag>
                                          </span>,
                                          'Revenue',
                                          revenueEventsSeries,
                                          {
                                              display:
                                                  revenueEventsSeries.length > 1
                                                      ? ChartDisplayType.ActionsAreaGraph
                                                      : ChartDisplayType.ActionsLineGraph,
                                          },
                                          {
                                              compareFilter: revenueEventsSeries.length > 1 ? undefined : compareFilter,
                                          }
                                      )
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
                                conversionGoal && conversionRevenueSeries.length
                                    ? createGraphsTrendsTab(
                                          GraphsTab.CONVERSION_REVENUE,
                                          <span>
                                              Conversion Revenue&nbsp;<LemonTag type="warning">BETA</LemonTag>
                                          </span>,
                                          'Conversion Revenue',
                                          conversionRevenueSeries
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
                        tabs: featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_FOR_MOBILE]
                            ? [
                                  createTableTab(
                                      TileId.PATHS,
                                      PathTab.SCREEN_NAME,
                                      'Screens',
                                      'Screen',
                                      WebStatsBreakdown.ScreenName,
                                      {},
                                      {}
                                  ),
                              ]
                            : (
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
                                              doPathCleaning: isPathCleaningEnabled,
                                              pathExtractionMethod,
                                          },
                                          {
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
                                                                  The conversion rate is the percentage of users who
                                                                  completed the conversion goal in this specific path.
                                                              </p>
                                                          ) : (
                                                              <p>
                                                                  The{' '}
                                                                  <Link to="https://posthog.com/docs/web-analytics/dashboard#bounce-rate">
                                                                      bounce rate
                                                                  </Link>{' '}
                                                                  indicates the percentage of users who left your page
                                                                  immediately after visiting without capturing any
                                                                  event.
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
                                              doPathCleaning: isPathCleaningEnabled,
                                              pathExtractionMethod,
                                          },
                                          {
                                              docs: {
                                                  url: 'https://posthog.com/docs/web-analytics/dashboard#paths',
                                                  title: 'Entry Path',
                                                  description: (
                                                      <div>
                                                          <p>
                                                              Entry paths are the paths a user session started, i.e. the
                                                              first path they saw when they opened your website.
                                                          </p>
                                                          {conversionGoal && (
                                                              <p>
                                                                  The conversion rate is the percentage of users who
                                                                  completed the conversion goal after the first path in
                                                                  their session being this path.
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
                                              doPathCleaning: isPathCleaningEnabled,
                                              pathExtractionMethod,
                                          },
                                          {
                                              docs: {
                                                  url: 'https://posthog.com/docs/web-analytics/dashboard#paths',
                                                  title: 'End Path',
                                                  description: (
                                                      <div>
                                                          End paths are the last path a user visited before their
                                                          session ended, i.e. the last path they saw before leaving your
                                                          website/closing the browser/turning their computer off.
                                                      </div>
                                                  ),
                                              },
                                          }
                                      ),
                                      {
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
                                                  conversionGoal,
                                                  orderBy: tablesOrderBy ?? undefined,
                                                  stripQueryParams: shouldStripQueryParams,
                                              },
                                              embedded: false,
                                              showActions: true,
                                              columns: ['url', 'visitors', 'clicks', 'cross_sell'],
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
                                      },
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
                                    control: (
                                        <div className="flex flex-row deprecated-space-x-2 font-medium">
                                            <span>Customize channel types</span>
                                            <LemonButton
                                                icon={<IconGear />}
                                                type="tertiary"
                                                status="alt"
                                                size="small"
                                                noPadding={true}
                                                tooltip="Customize channel types"
                                                to={urls.settings('environment-web-analytics', 'channel-type')}
                                            />
                                        </div>
                                    ),
                                    docs: {
                                        url: 'https://posthog.com/docs/data/channel-type',
                                        title: 'Channels',
                                        description: (
                                            <div>
                                                <p>
                                                    Channels are the different sources that bring traffic to your
                                                    website, e.g. Paid Search, Organic Social, Direct, etc.
                                                </p>
                                                <p>
                                                    You can also{' '}
                                                    <Link
                                                        to={urls.settings('environment-web-analytics', 'channel-type')}
                                                    >
                                                        create custom channel types
                                                    </Link>
                                                    , allowing you to further categorize your channels.
                                                </p>
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
                            createTableTab(
                                TileId.DEVICES,
                                DeviceTab.VIEWPORT,
                                'Viewports',
                                'Viewport',
                                WebStatsBreakdown.Viewport
                            ),
                        ],
                    },

                    {
                        kind: 'tabs',
                        tileId: TileId.GEOGRAPHY,
                        layout: {
                            colSpanClassName: 'md:col-span-full',
                        },
                        activeTabId:
                            geographyTab || (shouldShowGeoIPQueries ? GeographyTab.MAP : GeographyTab.LANGUAGES),
                        setTabId: actions.setGeographyTab,
                        tabs: (
                            [
                                shouldShowGeoIPQueries
                                    ? {
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
                                                  conversionGoal,
                                                  filterTestAccounts,
                                                  properties: webAnalyticsFilters,
                                                  tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                                              },
                                              hidePersonsModal: true,
                                              embedded: true,
                                          },
                                          insightProps: createInsightProps(TileId.GEOGRAPHY, GeographyTab.MAP),
                                          canOpenInsight: true,
                                      }
                                    : null,
                                shouldShowGeoIPQueries
                                    ? createTableTab(
                                          TileId.GEOGRAPHY,
                                          GeographyTab.COUNTRIES,
                                          'Countries',
                                          'Countries',
                                          WebStatsBreakdown.Country
                                      )
                                    : null,
                                shouldShowGeoIPQueries
                                    ? createTableTab(
                                          TileId.GEOGRAPHY,
                                          GeographyTab.REGIONS,
                                          'Regions',
                                          'Regions',
                                          WebStatsBreakdown.Region
                                      )
                                    : null,
                                shouldShowGeoIPQueries
                                    ? createTableTab(
                                          TileId.GEOGRAPHY,
                                          GeographyTab.CITIES,
                                          'Cities',
                                          'Cities',
                                          WebStatsBreakdown.City
                                      )
                                    : null,
                                createTableTab(
                                    TileId.GEOGRAPHY,
                                    GeographyTab.LANGUAGES,
                                    'Languages',
                                    'Languages',
                                    WebStatsBreakdown.Language
                                ),
                                createTableTab(
                                    TileId.GEOGRAPHY,
                                    GeographyTab.TIMEZONES,
                                    'Timezones',
                                    'Timezones',
                                    WebStatsBreakdown.Timezone
                                ),
                            ] as (TabsTileTab | null)[]
                        ).filter(isNotNil),
                    },
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
                                          retentionType: RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS,
                                          retentionReference: 'total',
                                          totalIntervals: isGreaterThanMd ? 8 : 5,
                                          period: RetentionPeriod.Week,
                                      },
                                      tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
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
                                                  You want the numbers to be the highest possible, suggesting that
                                                  people that come to your page continue coming to your page - and
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
                    {
                        kind: 'tabs',
                        tileId: TileId.ACTIVE_HOURS,
                        layout: {
                            colSpanClassName: 'md:col-span-full',
                        },
                        activeTabId: activeHoursTab,
                        setTabId: actions.setActiveHoursTab,
                        tabs: [
                            {
                                id: ActiveHoursTab.UNIQUE,
                                title: 'Active Hours',
                                linkText: 'Unique users',
                                canOpenModal: true,
                                canOpenInsight: !!featureFlags[FEATURE_FLAGS.CALENDAR_HEATMAP_INSIGHT],
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: '$pageview',
                                                name: '$pageview',
                                                math: BaseMathType.UniqueUsers,
                                                properties: webAnalyticsFilters,
                                            },
                                        ],
                                        dateRange,
                                        conversionGoal,
                                        tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                                        trendsFilter: {
                                            display: ChartDisplayType.CalendarHeatmap,
                                        },
                                    },
                                },
                                docs: {
                                    url: 'https://posthog.com/docs/web-analytics/dashboard#active-hours',
                                    title: 'Active hours - Unique users',
                                    description: (
                                        <>
                                            <div>
                                                <p>
                                                    Active hours displays a heatmap showing the number of unique users
                                                    who performed any pageview event, broken down by hour of the day and
                                                    day of the week.
                                                </p>
                                                <p>
                                                    Each cell represents the number of unique users during a specific
                                                    hour of a specific day. The "All" column aggregates totals for each
                                                    day, and the bottom row aggregates totals for each hour. The
                                                    bottom-right cell shows the grand total. The displayed time is based
                                                    on your project's date and time settings (UTC by default,
                                                    configurable in{' '}
                                                    <Link to={urls.settings('project', 'date-and-time')}>
                                                        project settings
                                                    </Link>
                                                    ).
                                                </p>
                                                <p>
                                                    <strong>Note:</strong> Selecting a time range longer than 7 days
                                                    will include additional occurrences of weekdays and hours,
                                                    potentially increasing the user counts in those buckets. For best
                                                    results, select 7 closed days or multiple of 7 closed day ranges.
                                                </p>
                                            </div>
                                        </>
                                    ),
                                },
                                insightProps: createInsightProps(TileId.ACTIVE_HOURS, ActiveHoursTab.UNIQUE),
                            },
                            {
                                id: ActiveHoursTab.TOTAL_EVENTS,
                                title: 'Active Hours',
                                linkText: 'Total pageviews',
                                canOpenModal: true,
                                canOpenInsight: !!featureFlags[FEATURE_FLAGS.CALENDAR_HEATMAP_INSIGHT],
                                query: {
                                    kind: NodeKind.InsightVizNode,
                                    source: {
                                        kind: NodeKind.TrendsQuery,
                                        series: [
                                            {
                                                kind: NodeKind.EventsNode,
                                                event: '$pageview',
                                                name: '$pageview',
                                                math: BaseMathType.TotalCount,
                                                properties: webAnalyticsFilters,
                                            },
                                        ],
                                        dateRange,
                                        conversionGoal,
                                        trendsFilter: {
                                            display: ChartDisplayType.CalendarHeatmap,
                                        },
                                        tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                                    },
                                },
                                docs: {
                                    url: 'https://posthog.com/docs/web-analytics/dashboard#active-hours',
                                    title: 'Active hours - Total pageviews',
                                    description: (
                                        <>
                                            <div>
                                                <p>
                                                    Active hours displays a heatmap showing the total number of
                                                    pageviews, broken down by hour of the day and day of the week.
                                                </p>
                                                <p>
                                                    Each cell represents the number of total pageviews during a specific
                                                    hour of a specific day. The "All" column aggregates totals for each
                                                    day, and the bottom row aggregates totals for each hour. The
                                                    bottom-right cell shows the grand total. The displayed time is based
                                                    on your project's date and time settings (UTC by default,
                                                    configurable in{' '}
                                                    <Link to={urls.settings('project', 'date-and-time')}>
                                                        project settings
                                                    </Link>
                                                    ).
                                                </p>
                                                <p>
                                                    <strong>Note:</strong> Selecting a time range longer than 7 days
                                                    will include additional occurrences of weekdays and hours,
                                                    potentially increasing the user counts in those buckets. For best
                                                    results, select 7 closed days or multiple of 7 closed day ranges.
                                                </p>
                                            </div>
                                        </>
                                    ),
                                },
                                insightProps: createInsightProps(TileId.ACTIVE_HOURS, ActiveHoursTab.TOTAL_EVENTS),
                            },
                        ],
                    },
                    // Hiding if conversionGoal is set already because values aren't representative
                    !conversionGoal
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
                                      orderBy: tablesOrderBy ?? undefined,
                                      filterTestAccounts,
                                      tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                                  },
                                  embedded: true,
                                  showActions: true,
                                  columns: ['breakdown_value', 'visitors', 'views', 'cross_sell'],
                              },
                              insightProps: createInsightProps(TileId.GOALS),
                              canOpenInsight: false,
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
                    !conversionGoal
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
                    !conversionGoal && errorTrackingQ
                        ? {
                              kind: 'error_tracking',
                              tileId: TileId.ERROR_TRACKING,
                              layout: {
                                  colSpanClassName: 'md:col-span-1',
                              },
                              query: errorTrackingQ,
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
                    !conversionGoal && featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_FRUSTRATING_PAGES_TILE]
                        ? {
                              kind: 'query',
                              title: 'Frustrating Pages',
                              tileId: TileId.FRUSTRATING_PAGES,
                              layout: {
                                  colSpanClassName: 'md:col-span-2',
                              },
                              query: {
                                  full: true,
                                  kind: NodeKind.DataTableNode,
                                  source: {
                                      kind: NodeKind.WebStatsTableQuery,
                                      breakdownBy: WebStatsBreakdown.FrustrationMetrics,
                                      dateRange,
                                      filterTestAccounts,
                                      properties: webAnalyticsFilters,
                                      compareFilter,
                                      limit: 10,
                                      doPathCleaning: isPathCleaningEnabled,
                                      pathExtractionMethod,
                                      tags: WEB_ANALYTICS_DEFAULT_QUERY_TAGS,
                                  },
                                  embedded: true,
                                  showActions: true,
                                  hiddenColumns: ['views'],
                              },
                              insightProps: createInsightProps(TileId.FRUSTRATING_PAGES, 'table'),
                              canOpenModal: true,
                              canOpenInsight: false,
                              docs: {
                                  title: 'Frustrating Pages',
                                  description: (
                                      <>
                                          <div>
                                              <p>
                                                  See which pages are causing frustration by monitoring rage clicks,
                                                  dead clicks, and errors.
                                              </p>
                                              <p>
                                                  <ul>
                                                      <li>
                                                          A dead click is a click that doesn't result in any action.
                                                          E.g. an image that looks like a button.
                                                      </li>
                                                      <li>
                                                          Rageclicks are collected when a user clicks on a static
                                                          element more than three times in a one-second window.
                                                      </li>
                                                      <li>
                                                          Errors are JavaScript exceptions that occur when users
                                                          interact with your site.
                                                      </li>
                                                  </ul>
                                              </p>
                                              <p>
                                                  These are captured automatically and can help identify broken
                                                  functionality, failed API calls, or other technical issues that
                                                  frustrate users.
                                              </p>
                                          </div>
                                      </>
                                  ),
                              },
                          }
                        : null,
                ]
                return allTiles
                    .filter(isNotNil)
                    .filter((tile) =>
                        preAggregatedEnabled ? TILES_ALLOWED_ON_PRE_AGGREGATED.includes(tile.tileId) : true
                    )
                    .filter((tile) => !hiddenTiles.includes(tile.tileId))
            },
        ],
        getNewInsightUrl: [(s) => [s.tiles], (tiles: WebAnalyticsTile[]) => getNewInsightUrlFactory(tiles)],
    })),

    // start the loaders after mounting the logic
    afterMount(({ actions }) => {
        actions.loadStatusCheck()
        actions.loadShouldShowGeoIPQueries()
    }),

    tabAwareActionToUrl(({ values }) => {
        const stateToUrl = (): string => {
            const searchParams = { ...router.values.searchParams }
            const urlParams = new URLSearchParams(searchParams)

            const {
                rawWebAnalyticsFilters,
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
                productTab,
                webVitalsPercentile,
                domainFilter,
                deviceTypeFilter,
                tileVisualizations,
            } = values

            // Make sure we're storing the raw filters only, or else we'll have issues with the domain/device type filters
            // spreading from their individual dropdowns to the global filters list
            if (rawWebAnalyticsFilters.length > 0) {
                urlParams.set('filters', JSON.stringify(rawWebAnalyticsFilters))
            }
            if (conversionGoal) {
                if ('actionId' in conversionGoal) {
                    urlParams.set('conversionGoal.actionId', conversionGoal.actionId.toString())
                } else {
                    urlParams.set('conversionGoal.customEventName', conversionGoal.customEventName)
                }
            } else {
                urlParams.delete('conversionGoal.actionId')
                urlParams.delete('conversionGoal.customEventName')
            }
            if (dateFrom !== INITIAL_DATE_FROM || dateTo !== INITIAL_DATE_TO || interval !== INITIAL_INTERVAL) {
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
            } else {
                urlParams.delete('compare_filter')
            }

            const { featureFlags } = featureFlagLogic.values
            const pageReportsEnabled = !!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_PAGE_REPORTS]

            if (productTab === ProductTab.WEB_VITALS) {
                urlParams.set('percentile', webVitalsPercentile)
            }
            if (domainFilter) {
                urlParams.set('domain', domainFilter)
            }
            if (deviceTypeFilter) {
                urlParams.set('device_type', deviceTypeFilter)
            } else {
                urlParams.delete('device_type')
            }
            if (tileVisualizations) {
                urlParams.set('tile_visualizations', JSON.stringify(tileVisualizations))
            }

            let basePath = '/web'
            if (pageReportsEnabled && productTab === ProductTab.PAGE_REPORTS) {
                basePath = '/web/page-reports'
            } else if (productTab === ProductTab.WEB_VITALS) {
                basePath = '/web/web-vitals'
            } else if (productTab === ProductTab.MARKETING) {
                basePath = '/web/marketing'
            }
            return `${basePath}${urlParams.toString() ? '?' + urlParams.toString() : ''}`
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
            setActiveHoursTab: stateToUrl,
            setCompareFilter: stateToUrl,
            setProductTab: stateToUrl,
            setWebVitalsPercentile: stateToUrl,
            setIsPathCleaningEnabled: stateToUrl,
            setPathExtractionMethod: stateToUrl,
            setDomainFilter: stateToUrl,
            setDeviceTypeFilter: stateToUrl,
            setTileVisualization: stateToUrl,
        }
    }),

    tabAwareUrlToAction(({ actions, values }) => {
        const toAction = (
            { productTab = ProductTab.ANALYTICS }: { productTab?: ProductTab },
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
                active_hours_tab,
                path_cleaning,
                path_extraction,
                filter_test_accounts,
                compare_filter,
                percentile,
                domain,
                device_type,
                tile_visualizations,
            }: Record<string, any>
        ): void => {
            const { featureFlags } = featureFlagLogic.values
            const pageReportsEnabled = !!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_PAGE_REPORTS]

            // If trying to access page reports but the feature flag is not enabled, redirect to analytics
            if (productTab === ProductTab.PAGE_REPORTS && !pageReportsEnabled) {
                productTab = ProductTab.ANALYTICS
            }

            if (
                ![ProductTab.ANALYTICS, ProductTab.WEB_VITALS, ProductTab.PAGE_REPORTS, ProductTab.MARKETING].includes(
                    productTab
                )
            ) {
                return
            }

            const parsedFilters = filters ? (isWebAnalyticsPropertyFilters(filters) ? filters : []) : undefined
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
            if (active_hours_tab && active_hours_tab !== values._activeHoursTab) {
                actions.setActiveHoursTab(active_hours_tab)
            }
            if (path_cleaning && path_cleaning !== values.isPathCleaningEnabled) {
                actions.setIsPathCleaningEnabled([true, 'true', 1, '1'].includes(path_cleaning))
            }
            if (path_extraction && path_extraction !== values.pathExtractionMethod) {
                actions.setPathExtractionMethod(path_extraction as WebStatsPathExtractionMethod)
            }
            if (filter_test_accounts && filter_test_accounts !== values.shouldFilterTestAccounts) {
                actions.setShouldFilterTestAccounts([true, 'true', 1, '1'].includes(filter_test_accounts))
            }
            if (
                compare_filter &&
                isCompareFilter(compare_filter) &&
                !objectsEqual(compare_filter, values.compareFilter)
            ) {
                actions.setCompareFilter(compare_filter)
            }
            if (productTab && productTab !== values.productTab) {
                actions.setProductTab(productTab)
            }
            if (percentile && percentile !== values.webVitalsPercentile) {
                actions.setWebVitalsPercentile(percentile as WebVitalsPercentile)
            }
            if (domain && domain !== values.domainFilter) {
                actions.setDomainFilter(domain === 'all' ? null : domain)
            }
            if (device_type && device_type !== values.deviceTypeFilter) {
                actions.setDeviceTypeFilter(device_type)
            }
            if (tile_visualizations && !objectsEqual(tile_visualizations, values.tileVisualizations)) {
                for (const [tileId, visualization] of Object.entries(tile_visualizations)) {
                    actions.setTileVisualization(tileId as TileId, visualization as TileVisualizationOption)
                }
            }
        }

        return { '/web': toAction, '/web/:productTab': toAction, '/web/page-reports': toAction }
    }),

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
                        actions.setConversionGoalWarning
                    ),
            ],
            [teamLogic.actionTypes.updateCurrentTeam]: async (action) => {
                const isPreAggregatedEnabled =
                    values.featureFlags[FEATURE_FLAGS.SETTINGS_WEB_ANALYTICS_PRE_AGGREGATED_TABLES] &&
                    action?.modifiers?.useWebAnalyticsPreAggregatedTables
                const hasConversionGoalPreAggFlag =
                    values.featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_CONVERSION_GOAL_PREAGG]

                if (isPreAggregatedEnabled && values.conversionGoal && !hasConversionGoalPreAggFlag) {
                    actions.setConversionGoal(null)
                    lemonToast.info(
                        'Your conversion goal has been cleared as the new query engine does not support it (yet!)'
                    )
                }
            },
        }
    }),
    afterMount(({ actions, values }) => {
        checkCustomEventConversionGoalHasSessionIdsHelper(
            values.conversionGoal,
            undefined,
            actions.setConversionGoalWarning
        ).catch(() => {
            // ignore, this warning is just a nice-to-have, no point showing an error to the user
        })
    }),
])

const checkCustomEventConversionGoalHasSessionIdsHelper = async (
    conversionGoal: WebAnalyticsConversionGoal | null,
    breakpoint: BreakPointFunction | undefined,
    setConversionGoalWarning: (warning: ConversionGoalWarning | null) => void
): Promise<void> => {
    if (!conversionGoal || !('customEventName' in conversionGoal) || !conversionGoal.customEventName) {
        setConversionGoalWarning(null)
        return
    }
    const { customEventName } = conversionGoal
    // check if we have any conversion events from the last week without sessions ids

    const response = await hogqlQuery(
        hogql`select count()
              from events
              where timestamp >= (now() - toIntervalHour(24))
                AND ($session_id IS NULL
                 OR $session_id = '')
                AND event = {event}`,
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
