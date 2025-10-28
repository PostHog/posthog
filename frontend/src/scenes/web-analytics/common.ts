import { BreakPointFunction } from 'kea'

import { PostHogComDocsURL } from 'lib/lemon-ui/Link/Link'
import { UnexpectedNeverError, getDefaultInterval } from 'lib/utils'

import { hogqlQuery } from '~/queries/query'
import {
    BreakdownFilter,
    QueryLogTags,
    QuerySchema,
    WebAnalyticsConversionGoal,
    WebAnalyticsPropertyFilters,
    WebStatsBreakdown,
} from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { InsightLogicProps, ProductKey, PropertyFilterType, PropertyMathType } from '~/types'

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
    ACTIVE_HOURS = 'ACTIVE_HOURS',
    RETENTION = 'RETENTION',
    REPLAY = 'REPLAY',
    ERROR_TRACKING = 'ERROR_TRACKING',
    GOALS = 'GOALS',
    WEB_VITALS = 'WEB_VITALS',
    WEB_VITALS_PATH_BREAKDOWN = 'WEB_VITALS_PATH_BREAKDOWN',
    FRUSTRATING_PAGES = 'FRUSTRATING_PAGES',
    MARKETING_OVERVIEW = 'MARKETING_OVERVIEW',

    // Page Report Tiles to avoid conflicts with web analytics
    PAGE_REPORTS_COMBINED_METRICS_CHART_SECTION = 'PR_COMBINED_METRICS_CHART_SECTION',
    PAGE_REPORTS_PATHS_SECTION = 'PR_PATHS_SECTION',
    PAGE_REPORTS_DEVICE_INFORMATION_SECTION = 'PR_DEVICE_INFORMATION_SECTION',
    PAGE_REPORTS_TRAFFIC_SECTION = 'PR_TRAFFIC_SECTION',
    PAGE_REPORTS_GEOGRAPHY_SECTION = 'PR_GEOGRAPHY_SECTION',
    PAGE_REPORTS_TOP_EVENTS_SECTION = 'PR_TOP_EVENTS_SECTION',
    PAGE_REPORTS_COMBINED_METRICS_CHART = 'PR_COMBINED_METRICS_CHART',
    PAGE_REPORTS_ENTRY_PATHS = 'PR_ENTRY_PATHS',
    PAGE_REPORTS_EXIT_PATHS = 'PR_EXIT_PATHS',
    PAGE_REPORTS_OUTBOUND_CLICKS = 'PR_OUTBOUND_CLICKS',
    PAGE_REPORTS_CHANNELS = 'PR_CHANNELS',
    PAGE_REPORTS_REFERRERS = 'PR_REFERRERS',
    PAGE_REPORTS_DEVICE_TYPES = 'PR_DEVICE_TYPES',
    PAGE_REPORTS_BROWSERS = 'PR_BROWSERS',
    PAGE_REPORTS_OPERATING_SYSTEMS = 'PR_OPERATING_SYSTEMS',
    PAGE_REPORTS_COUNTRIES = 'PR_COUNTRIES',
    PAGE_REPORTS_REGIONS = 'PR_REGIONS',
    PAGE_REPORTS_CITIES = 'PR_CITIES',
    PAGE_REPORTS_TIMEZONES = 'PR_TIMEZONES',
    PAGE_REPORTS_LANGUAGES = 'PR_LANGUAGES',
    PAGE_REPORTS_TOP_EVENTS = 'PR_TOP_EVENTS',
    PAGE_REPORTS_PREVIOUS_PAGE = 'PR_PREVIOUS_PAGE',

    // Marketing Tiles
    MARKETING = 'MARKETING',
    MARKETING_CAMPAIGN_BREAKDOWN = 'MARKETING_CAMPAIGN_BREAKDOWN',
}

export enum ProductTab {
    ANALYTICS = 'analytics',
    WEB_VITALS = 'web-vitals',
    PAGE_REPORTS = 'page-reports',
    SESSION_ATTRIBUTION_EXPLORER = 'session-attribution-explorer',
    MARKETING = 'marketing',
}

export type DeviceType = 'Desktop' | 'Mobile'

export type WebVitalsPercentile = PropertyMathType.P75 | PropertyMathType.P90 | PropertyMathType.P99

export const loadPriorityMap: Record<TileId, number> = {
    [TileId.OVERVIEW]: 1,
    [TileId.GRAPHS]: 2,
    [TileId.PATHS]: 3,
    [TileId.SOURCES]: 4,
    [TileId.DEVICES]: 5,
    [TileId.GEOGRAPHY]: 6,
    [TileId.ACTIVE_HOURS]: 7,
    [TileId.RETENTION]: 8,
    [TileId.REPLAY]: 9,
    [TileId.ERROR_TRACKING]: 10,
    [TileId.GOALS]: 11,
    [TileId.WEB_VITALS]: 12,
    [TileId.WEB_VITALS_PATH_BREAKDOWN]: 13,
    [TileId.FRUSTRATING_PAGES]: 14,

    // Page Report Sections
    [TileId.PAGE_REPORTS_COMBINED_METRICS_CHART_SECTION]: 1,
    [TileId.PAGE_REPORTS_PATHS_SECTION]: 2,
    [TileId.PAGE_REPORTS_DEVICE_INFORMATION_SECTION]: 3,
    [TileId.PAGE_REPORTS_TRAFFIC_SECTION]: 4,
    [TileId.PAGE_REPORTS_GEOGRAPHY_SECTION]: 5,
    [TileId.PAGE_REPORTS_TOP_EVENTS_SECTION]: 6,

    // Page Report Tiles
    [TileId.PAGE_REPORTS_COMBINED_METRICS_CHART]: 1,
    [TileId.PAGE_REPORTS_ENTRY_PATHS]: 2,
    [TileId.PAGE_REPORTS_EXIT_PATHS]: 3,
    [TileId.PAGE_REPORTS_OUTBOUND_CLICKS]: 4,
    [TileId.PAGE_REPORTS_CHANNELS]: 5,
    [TileId.PAGE_REPORTS_REFERRERS]: 6,
    [TileId.PAGE_REPORTS_PREVIOUS_PAGE]: 7,
    [TileId.PAGE_REPORTS_DEVICE_TYPES]: 8,
    [TileId.PAGE_REPORTS_BROWSERS]: 9,
    [TileId.PAGE_REPORTS_OPERATING_SYSTEMS]: 10,
    [TileId.PAGE_REPORTS_COUNTRIES]: 11,
    [TileId.PAGE_REPORTS_REGIONS]: 12,
    [TileId.PAGE_REPORTS_CITIES]: 13,
    [TileId.PAGE_REPORTS_TIMEZONES]: 14,
    [TileId.PAGE_REPORTS_LANGUAGES]: 15,
    [TileId.PAGE_REPORTS_TOP_EVENTS]: 16,

    // Marketing Tiles
    [TileId.MARKETING_OVERVIEW]: 1,
    [TileId.MARKETING]: 2,
    [TileId.MARKETING_CAMPAIGN_BREAKDOWN]: 3,
}

// To enable a tile here, you must update the QueryRunner to support it
// or make sure it can load in a decent time (which event-only tiles usually do).
// We filter them here to enable a faster experience for the user as the
// tiles that don't support pre-aggregated tables take a longer time to load
// and will effectively block other queries to load because of the concurrencyController
export const TILES_ALLOWED_ON_PRE_AGGREGATED = [
    TileId.OVERVIEW,
    TileId.PATHS,
    TileId.SOURCES,
    TileId.DEVICES,

    // Not 100% supported yet but they are fast enough that we can show them
    TileId.GRAPHS,
    TileId.GEOGRAPHY,
]

export interface BaseTile {
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
    control?: JSX.Element
    insightProps: InsightLogicProps
    canOpenModal?: boolean
    canOpenInsight?: boolean
}

export interface TabsTileTab {
    id: string
    title: string | JSX.Element
    linkText: string | JSX.Element
    query: QuerySchema
    showIntervalSelect?: boolean
    control?: JSX.Element
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

export interface SectionTile extends BaseTile {
    kind: 'section'
    title?: string
    tiles: WebAnalyticsTile[]
}

export type WebAnalyticsTile = QueryTile | TabsTile | ReplayTile | ErrorTrackingTile | SectionTile

export enum GraphsTab {
    UNIQUE_USERS = 'UNIQUE_USERS',
    PAGE_VIEWS = 'PAGE_VIEWS',
    NUM_SESSION = 'NUM_SESSION',
    UNIQUE_CONVERSIONS = 'UNIQUE_CONVERSIONS',
    TOTAL_CONVERSIONS = 'TOTAL_CONVERSIONS',
    CONVERSION_RATE = 'CONVERSION_RATE',
    REVENUE_EVENTS = 'REVENUE_EVENTS',
    CONVERSION_REVENUE = 'CONVERSION_REVENUE',
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
    VIEWPORT = 'VIEWPORT',
}

export enum PathTab {
    PATH = 'PATH',
    INITIAL_PATH = 'INITIAL_PATH',
    END_PATH = 'END_PATH',
    EXIT_CLICK = 'EXIT_CLICK',
    SCREEN_NAME = 'SCREEN_NAME',
    PREVIOUS_PATH = 'PREVIOUS_PATH',
    NEXT_PATH = 'NEXT_PATH',
}

export enum GeographyTab {
    MAP = 'MAP',
    COUNTRIES = 'COUNTRIES',
    REGIONS = 'REGIONS',
    CITIES = 'CITIES',
    TIMEZONES = 'TIMEZONES',
    HEATMAP = 'HEATMAP',
    LANGUAGES = 'LANGUAGES',
}

export enum ActiveHoursTab {
    UNIQUE = 'UNIQUE',
    TOTAL_EVENTS = 'TOTAL_EVENTS',
}

export enum ConversionGoalWarning {
    CustomEventWithNoSessionId = 'CustomEventWithNoSessionId',
}

export interface WebAnalyticsStatusCheck {
    isSendingWebVitals: boolean
    isSendingPageViews: boolean
    isSendingPageLeaves: boolean
    isSendingPageLeavesScroll: boolean
    hasAuthorizedUrls: boolean
}

export type TileVisualizationOption = 'table' | 'graph'

export const webStatsBreakdownToPropertyName = (
    breakdownBy: WebStatsBreakdown
):
    | { key: string; type: PropertyFilterType.Person | PropertyFilterType.Event | PropertyFilterType.Session }
    | undefined => {
    switch (breakdownBy) {
        case WebStatsBreakdown.Page:
            return { key: '$pathname', type: PropertyFilterType.Event }
        case WebStatsBreakdown.InitialPage:
            return { key: '$entry_pathname', type: PropertyFilterType.Session }
        case WebStatsBreakdown.ExitPage:
            return { key: '$end_pathname', type: PropertyFilterType.Session }
        case WebStatsBreakdown.PreviousPage:
            return undefined // could be $prev_pageview_pathname or $referrer
        case WebStatsBreakdown.ExitClick:
            return { key: '$last_external_click_url', type: PropertyFilterType.Session }
        case WebStatsBreakdown.ScreenName:
            return { key: '$screen_name', type: PropertyFilterType.Event }
        case WebStatsBreakdown.InitialChannelType:
            return { key: '$channel_type', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialReferringDomain:
            return { key: '$entry_referring_domain', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialUTMSource:
            return { key: '$entry_utm_source', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialUTMCampaign:
            return { key: '$entry_utm_campaign', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialUTMMedium:
            return { key: '$entry_utm_medium', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialUTMContent:
            return { key: '$entry_utm_content', type: PropertyFilterType.Session }
        case WebStatsBreakdown.InitialUTMTerm:
            return { key: '$entry_utm_term', type: PropertyFilterType.Session }
        case WebStatsBreakdown.Browser:
            return { key: '$browser', type: PropertyFilterType.Event }
        case WebStatsBreakdown.OS:
            return { key: '$os', type: PropertyFilterType.Event }
        case WebStatsBreakdown.Viewport:
            return { key: '$viewport', type: PropertyFilterType.Event }
        case WebStatsBreakdown.DeviceType:
            return { key: '$device_type', type: PropertyFilterType.Event }
        case WebStatsBreakdown.Country:
            return { key: '$geoip_country_code', type: PropertyFilterType.Event }
        case WebStatsBreakdown.Region:
            return { key: '$geoip_subdivision_1_code', type: PropertyFilterType.Event }
        case WebStatsBreakdown.City:
            return { key: '$geoip_city_name', type: PropertyFilterType.Event }
        case WebStatsBreakdown.Timezone:
            return { key: '$timezone', type: PropertyFilterType.Event }
        case WebStatsBreakdown.Language:
            return { key: '$browser_language', type: PropertyFilterType.Event }
        case WebStatsBreakdown.FrustrationMetrics:
            return { key: '$pathname', type: PropertyFilterType.Event }
        case WebStatsBreakdown.InitialUTMSourceMediumCampaign:
            return undefined
        default:
            throw new UnexpectedNeverError(breakdownBy)
    }
}

export const getWebAnalyticsBreakdownFilter = (breakdown: WebStatsBreakdown): BreakdownFilter | undefined => {
    const property = webStatsBreakdownToPropertyName(breakdown)

    if (!property) {
        return undefined
    }

    return {
        breakdown_type: property.type,
        breakdown: property.key,
    }
}

export const GEOIP_TEMPLATE_IDS = ['template-geoip', 'plugin-posthog-plugin-geoip']

export const WEB_ANALYTICS_DATA_COLLECTION_NODE_ID = 'web-analytics'

export const INITIAL_WEB_ANALYTICS_FILTER = [] as WebAnalyticsPropertyFilters
export const INITIAL_DATE_FROM = '-7d' as string | null
export const INITIAL_DATE_TO = null as string | null
export const INITIAL_INTERVAL = getDefaultInterval(INITIAL_DATE_FROM, INITIAL_DATE_TO)

export const WEB_ANALYTICS_DEFAULT_QUERY_TAGS: QueryLogTags = {
    productKey: ProductKey.WEB_ANALYTICS,
}

export const MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS: QueryLogTags = {
    productKey: ProductKey.MARKETING_ANALYTICS,
}

export const checkCustomEventConversionGoalHasSessionIdsHelper = async (
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
        hogql`select count() from events where timestamp >= (now() - toIntervalHour(24)) AND ($session_id IS NULL OR $session_id = '') AND event = {event}`,
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

export const eventPropertiesToPathClean = new Set(['$pathname', '$current_url', '$prev_pageview_pathname'])
export const sessionPropertiesToPathClean = new Set([
    '$entry_pathname',
    '$end_pathname',
    '$entry_current_url',
    '$end_current_url',
])
export const personPropertiesToPathClean = new Set(['$initial_pathname', '$initial_current_url'])

// Utility function to map SQL/internal column names to UI-friendly display names
export const getDisplayColumnName = (column: string, breakdownBy?: WebStatsBreakdown): string => {
    // Strip the "context.columns." prefix if present
    const baseColumn = column.replace(/^context\.columns\./, '')

    // Handle known metric columns first (these should always show their metric names)
    const metricMappings: Record<string, string> = {
        visitors: 'Visitors',
        views: 'Views',
        sessions: 'Sessions',
        bounce_rate: 'Bounce Rate',
        session_duration: 'Session Duration',
        total_pageviews: 'Total Pageviews',
        unique_visitors: 'Unique Visitors',
        scroll_gt80_percentage: 'Scroll Depth >80%',
        rage_clicks: 'Rage Clicks',
    }

    if (metricMappings[baseColumn]) {
        return metricMappings[baseColumn]
    }

    // Handle breakdown column - only if this is the breakdown_value column and breakdownBy is defined
    if (baseColumn === 'breakdown_value' && breakdownBy !== undefined) {
        switch (breakdownBy) {
            case WebStatsBreakdown.Page:
                return 'Path'
            case WebStatsBreakdown.InitialPage:
                return 'Initial Path'
            case WebStatsBreakdown.ExitPage:
                return 'End Path'
            case WebStatsBreakdown.PreviousPage:
                return 'Previous Page'
            case WebStatsBreakdown.ExitClick:
                return 'Exit Click'
            case WebStatsBreakdown.ScreenName:
                return 'Screen Name'
            case WebStatsBreakdown.InitialChannelType:
                return 'Channel Type'
            case WebStatsBreakdown.InitialReferringDomain:
                return 'Referring Domain'
            case WebStatsBreakdown.InitialUTMSource:
                return 'UTM Source'
            case WebStatsBreakdown.InitialUTMCampaign:
                return 'UTM Campaign'
            case WebStatsBreakdown.InitialUTMMedium:
                return 'UTM Medium'
            case WebStatsBreakdown.InitialUTMTerm:
                return 'UTM Term'
            case WebStatsBreakdown.InitialUTMContent:
                return 'UTM Content'
            case WebStatsBreakdown.Browser:
                return 'Browser'
            case WebStatsBreakdown.OS:
                return 'OS'
            case WebStatsBreakdown.Viewport:
                return 'Viewport'
            case WebStatsBreakdown.DeviceType:
                return 'Device Type'
            case WebStatsBreakdown.Country:
                return 'Country'
            case WebStatsBreakdown.Region:
                return 'Region'
            case WebStatsBreakdown.City:
                return 'City'
            case WebStatsBreakdown.Timezone:
                return 'Timezone'
            case WebStatsBreakdown.Language:
                return 'Language'
            case WebStatsBreakdown.FrustrationMetrics:
                return 'URL'
            case WebStatsBreakdown.InitialUTMSourceMediumCampaign:
                return 'Source / Medium / Campaign'
        }
    }

    // Return base column name if no mapping found
    return baseColumn
}
