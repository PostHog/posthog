// Kernel types below are authored in frontend/src/queries/schema (x-schema-source:
// posthog.schema.*) — aliased instead of re-emitting a lossy generated copy.
import type {
    AccountsQuery,
    AccountsQueryResponse,
    ActionConversionGoal,
    ActionsNode,
    ActorsQuery,
    ActorsQueryResponse,
    BoxPlotDatum,
    Breakdown,
    BreakdownFilter,
    CalendarHeatmapFilter,
    ChartAxis,
    ChartSettings,
    ChartSettingsDisplay,
    ChartSettingsFormatting,
    ClickhouseQueryProgress,
    CompareFilter,
    ConditionalFormattingRule,
    CustomChannelCondition,
    CustomChannelRule,
    CustomEventConversionGoal,
    DataTableNode,
    DataTableNodeViewPropsContext,
    DataVisualizationNode,
    DataWarehouseEventsModifier,
    DataWarehouseNode,
    DataWarehouseSyncWarning,
    DateRange,
    EndpointsUsageTableQuery,
    EndpointsUsageTableQueryResponse,
    ErrorTrackingCorrelatedIssue,
    ErrorTrackingExternalReference,
    ErrorTrackingExternalReferenceIntegration,
    ErrorTrackingIssue,
    ErrorTrackingIssueAggregations,
    ErrorTrackingIssueAssignee,
    ErrorTrackingIssueCohort,
    ErrorTrackingIssueCorrelationQuery,
    ErrorTrackingIssueCorrelationQueryResponse,
    ErrorTrackingPendingFingerprintIssueStateUpdate,
    ErrorTrackingQuery,
    ErrorTrackingQueryResponse,
    EventDefinition,
    EventOddsRatioSerialized,
    EventsNode,
    EventsQuery,
    EventsQueryActionStep,
    EventsQueryResponse,
    ExperimentActorsQuery,
    ExperimentBreakdownResult,
    ExperimentDataWarehouseNode,
    ExperimentEventExposureConfig,
    ExperimentFunnelMetric,
    ExperimentFunnelsQuery,
    ExperimentFunnelsQueryResponse,
    ExperimentMeanMetric,
    ExperimentMetricOutlierHandling,
    ExperimentQuery,
    ExperimentQueryResponse,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    ExperimentStatsBaseValidated,
    ExperimentTrendsQuery,
    ExperimentTrendsQueryResponse,
    ExperimentVariantFunnelsBaseStats,
    ExperimentVariantResultBayesian,
    ExperimentVariantResultFrequentist,
    ExperimentVariantTrendsBaseStats,
    FunnelCorrelationActorsQuery,
    FunnelCorrelationQuery,
    FunnelCorrelationResponse,
    FunnelCorrelationResult,
    FunnelExclusionActionsNode,
    FunnelExclusionEventsNode,
    FunnelPathsFilter,
    FunnelsActorsQuery,
    FunnelsDataWarehouseNode,
    FunnelsFilter,
    FunnelsQuery,
    FunnelsQueryResponse,
    GoalLine,
    GroupNode,
    GroupsQuery,
    GroupsQueryResponse,
    HeatmapGradientStop,
    HeatmapSettings,
    HogQLFilters,
    HogQLMetadataResponse,
    HogQLNotice,
    HogQLQuery,
    HogQLQueryModifiers,
    HogQLQueryResponse,
    HogQLVariable,
    HogQuery,
    HogQueryResponse,
    InsightActorsQuery,
    InsightVizNode,
    IntegrationFilter,
    LLMTrace,
    LLMTraceEvent,
    LLMTracePerson,
    LifecycleDataWarehouseNode,
    LifecycleFilter,
    LifecycleQuery,
    LifecycleQueryResponse,
    MarketingAnalyticsAggregatedQuery,
    MarketingAnalyticsAggregatedQueryResponse,
    MarketingAnalyticsItem,
    MarketingAnalyticsTableQuery,
    MarketingAnalyticsTableQueryResponse,
    NonIntegratedConversionsTableQuery,
    NonIntegratedConversionsTableQueryResponse,
    PathsFilter,
    PathsLink,
    PathsQuery,
    PathsQueryResponse,
    PersonsNode,
    QueryLogTags,
    QueryStatus,
    QueryTiming,
    ResolvedDateRangeResponse,
    ResultCustomizationByPosition,
    ResultCustomizationByValue,
    RetentionFilter,
    RetentionQuery,
    RetentionQueryResponse,
    RetentionResult,
    RetentionValue,
    RevenueAnalyticsBreakdown,
    RevenueAnalyticsGrossRevenueQuery,
    RevenueAnalyticsGrossRevenueQueryResponse,
    RevenueAnalyticsMRRQuery,
    RevenueAnalyticsMRRQueryResponse,
    RevenueAnalyticsMRRQueryResultItem,
    RevenueAnalyticsMetricsQuery,
    RevenueAnalyticsMetricsQueryResponse,
    RevenueAnalyticsOverviewItem,
    RevenueAnalyticsOverviewQuery,
    RevenueAnalyticsOverviewQueryResponse,
    RevenueAnalyticsTopCustomersQuery,
    RevenueAnalyticsTopCustomersQueryResponse,
    RevenueCurrencyPropertyConfig,
    RevenueExampleDataWarehouseTablesQuery,
    RevenueExampleDataWarehouseTablesQueryResponse,
    RevenueExampleEventsQuery,
    RevenueExampleEventsQueryResponse,
    SamplingRate,
    SessionAttributionExplorerQuery,
    SessionAttributionExplorerQueryResponse,
    SessionData,
    SessionsQuery,
    SessionsQueryResponse,
    StickinessActorsQuery,
    StickinessCriteria,
    StickinessFilter,
    StickinessQuery,
    StickinessQueryResponse,
    TableSettings,
    TraceQuery,
    TraceQueryResponse,
    TracesQuery,
    TracesQueryResponse,
    TrendsFilter,
    TrendsFormulaNode,
    TrendsQuery,
    TrendsQueryResponse,
    VizSpecificOptions,
    WebAnalyticsSampling,
    WebExternalClicksTableQuery,
    WebExternalClicksTableQueryResponse,
    WebGoalsQuery,
    WebGoalsQueryResponse,
    WebOverviewItem,
    WebOverviewQuery,
    WebOverviewQueryResponse,
    WebStatsTableQuery,
    WebStatsTableQueryResponse,
    WebVitalsPathBreakdownQuery,
    WebVitalsPathBreakdownQueryResponse,
    WebVitalsPathBreakdownResult,
    WebVitalsPathBreakdownResultItem,
    WebVitalsQuery,
    YAxisSettings,
} from '~/queries/schema/schema-general'
import type {
    CohortPropertyFilter,
    DataWarehousePersonPropertyFilter,
    DataWarehousePropertyFilter,
    ElementPropertyFilter,
    EmptyPropertyFilter,
    ErrorTrackingIssueFilter,
    EventMetadataPropertyFilter,
    EventPropertyFilter,
    FeaturePropertyFilter,
    FlagPropertyFilter,
    GroupPropertyFilter,
    HogQLPropertyFilter,
    LogEntryPropertyFilter,
    LogPropertyFilter,
    PathCleaningFilter,
    PersonPropertyFilter,
    PropertyGroupFilter,
    PropertyGroupFilterValue,
    RecordingPropertyFilter,
    RetentionEntity,
    RevenueAnalyticsPropertyFilter,
    SessionPropertyFilter,
    SpanPropertyFilter,
    WorkflowVariablePropertyFilter,
} from '~/types'

export type AccountsQueryApi = AccountsQuery
export type AccountsQueryResponseApi = AccountsQueryResponse
export type ActionConversionGoalApi = ActionConversionGoal
export type ActionsNodeApi = ActionsNode
export type ActorsQueryApi = ActorsQuery
export type ActorsQueryResponseApi = ActorsQueryResponse
export type BoxPlotDatumApi = BoxPlotDatum
export type BreakdownApi = Breakdown
export type BreakdownFilterApi = BreakdownFilter
export type CalendarHeatmapFilterApi = CalendarHeatmapFilter
export type ChartAxisApi = ChartAxis
export type ChartSettingsApi = ChartSettings
export type ChartSettingsDisplayApi = ChartSettingsDisplay
export type ChartSettingsFormattingApi = ChartSettingsFormatting
export type ClickhouseQueryProgressApi = ClickhouseQueryProgress
export type CohortPropertyFilterApi = CohortPropertyFilter
export type CompareFilterApi = CompareFilter
export type ConditionalFormattingRuleApi = ConditionalFormattingRule
export type CustomChannelConditionApi = CustomChannelCondition
export type CustomChannelRuleApi = CustomChannelRule
export type CustomEventConversionGoalApi = CustomEventConversionGoal
export type DataTableNodeApi = DataTableNode
export type DataTableNodeViewPropsContextApi = DataTableNodeViewPropsContext
export type DataVisualizationNodeApi = DataVisualizationNode
export type DataWarehouseEventsModifierApi = DataWarehouseEventsModifier
export type DataWarehouseNodeApi = DataWarehouseNode
export type DataWarehousePersonPropertyFilterApi = DataWarehousePersonPropertyFilter
export type DataWarehousePropertyFilterApi = DataWarehousePropertyFilter
export type DataWarehouseSyncWarningApi = DataWarehouseSyncWarning
export type DateRangeApi = DateRange
export type ElementPropertyFilterApi = ElementPropertyFilter
export type EmptyPropertyFilterApi = EmptyPropertyFilter
export type EndpointsUsageTableQueryApi = EndpointsUsageTableQuery
export type EndpointsUsageTableQueryResponseApi = EndpointsUsageTableQueryResponse
export type ErrorTrackingCorrelatedIssueApi = ErrorTrackingCorrelatedIssue
export type ErrorTrackingExternalReferenceApi = ErrorTrackingExternalReference
export type ErrorTrackingExternalReferenceIntegrationApi = ErrorTrackingExternalReferenceIntegration
export type ErrorTrackingIssueAggregationsApi = ErrorTrackingIssueAggregations
export type ErrorTrackingIssueApi = ErrorTrackingIssue
export type ErrorTrackingIssueAssigneeApi = ErrorTrackingIssueAssignee
export type ErrorTrackingIssueCohortApi = ErrorTrackingIssueCohort
export type ErrorTrackingIssueCorrelationQueryApi = ErrorTrackingIssueCorrelationQuery
export type ErrorTrackingIssueCorrelationQueryResponseApi = ErrorTrackingIssueCorrelationQueryResponse
export type ErrorTrackingIssueFilterApi = ErrorTrackingIssueFilter
export type ErrorTrackingPendingFingerprintIssueStateUpdateApi = ErrorTrackingPendingFingerprintIssueStateUpdate
export type ErrorTrackingQueryApi = ErrorTrackingQuery
export type ErrorTrackingQueryResponseApi = ErrorTrackingQueryResponse
export type EventDefinitionApi = EventDefinition
export type EventMetadataPropertyFilterApi = EventMetadataPropertyFilter
export type EventOddsRatioSerializedApi = EventOddsRatioSerialized
export type EventPropertyFilterApi = EventPropertyFilter
export type EventsNodeApi = EventsNode
export type EventsQueryActionStepApi = EventsQueryActionStep
export type EventsQueryApi = EventsQuery
export type EventsQueryResponseApi = EventsQueryResponse
export type ExperimentActorsQueryApi = ExperimentActorsQuery
export type ExperimentBreakdownResultApi = ExperimentBreakdownResult
export type ExperimentDataWarehouseNodeApi = ExperimentDataWarehouseNode
export type ExperimentEventExposureConfigApi = ExperimentEventExposureConfig
export type ExperimentFunnelMetricApi = ExperimentFunnelMetric
export type ExperimentFunnelsQueryApi = ExperimentFunnelsQuery
export type ExperimentFunnelsQueryResponseApi = ExperimentFunnelsQueryResponse
export type ExperimentMeanMetricApi = ExperimentMeanMetric
export type ExperimentMetricOutlierHandlingApi = ExperimentMetricOutlierHandling
export type ExperimentQueryApi = ExperimentQuery
export type ExperimentQueryResponseApi = ExperimentQueryResponse
export type ExperimentRatioMetricApi = ExperimentRatioMetric
export type ExperimentRetentionMetricApi = ExperimentRetentionMetric
export type ExperimentStatsBaseValidatedApi = ExperimentStatsBaseValidated
export type ExperimentTrendsQueryApi = ExperimentTrendsQuery
export type ExperimentTrendsQueryResponseApi = ExperimentTrendsQueryResponse
export type ExperimentVariantFunnelsBaseStatsApi = ExperimentVariantFunnelsBaseStats
export type ExperimentVariantResultBayesianApi = ExperimentVariantResultBayesian
export type ExperimentVariantResultFrequentistApi = ExperimentVariantResultFrequentist
export type ExperimentVariantTrendsBaseStatsApi = ExperimentVariantTrendsBaseStats
export type FeaturePropertyFilterApi = FeaturePropertyFilter
export type FlagPropertyFilterApi = FlagPropertyFilter
export type FunnelCorrelationActorsQueryApi = FunnelCorrelationActorsQuery
export type FunnelCorrelationQueryApi = FunnelCorrelationQuery
export type FunnelCorrelationResponseApi = FunnelCorrelationResponse
export type FunnelCorrelationResultApi = FunnelCorrelationResult
export type FunnelExclusionActionsNodeApi = FunnelExclusionActionsNode
export type FunnelExclusionEventsNodeApi = FunnelExclusionEventsNode
export type FunnelPathsFilterApi = FunnelPathsFilter
export type FunnelsActorsQueryApi = FunnelsActorsQuery
export type FunnelsDataWarehouseNodeApi = FunnelsDataWarehouseNode
export type FunnelsFilterApi = FunnelsFilter
export type FunnelsQueryApi = FunnelsQuery
export type FunnelsQueryResponseApi = FunnelsQueryResponse
export type GoalLineApi = GoalLine
export type GroupNodeApi = GroupNode
export type GroupPropertyFilterApi = GroupPropertyFilter
export type GroupsQueryApi = GroupsQuery
export type GroupsQueryResponseApi = GroupsQueryResponse
export type HeatmapGradientStopApi = HeatmapGradientStop
export type HeatmapSettingsApi = HeatmapSettings
export type HogQLFiltersApi = HogQLFilters
export type HogQLMetadataResponseApi = HogQLMetadataResponse
export type HogQLNoticeApi = HogQLNotice
export type HogQLPropertyFilterApi = HogQLPropertyFilter
export type HogQLQueryApi = HogQLQuery
export type HogQLQueryModifiersApi = HogQLQueryModifiers
export type HogQLQueryResponseApi = HogQLQueryResponse
export type HogQLVariableApi = HogQLVariable
export type HogQueryApi = HogQuery
export type HogQueryResponseApi = HogQueryResponse
export type InsightActorsQueryApi = InsightActorsQuery
export type InsightVizNodeApi = InsightVizNode
export type IntegrationFilterApi = IntegrationFilter
export type LLMTraceApi = LLMTrace
export type LLMTraceEventApi = LLMTraceEvent
export type LLMTracePersonApi = LLMTracePerson
export type LifecycleDataWarehouseNodeApi = LifecycleDataWarehouseNode
export type LifecycleFilterApi = LifecycleFilter
export type LifecycleQueryApi = LifecycleQuery
export type LifecycleQueryResponseApi = LifecycleQueryResponse
export type LogEntryPropertyFilterApi = LogEntryPropertyFilter
export type LogPropertyFilterApi = LogPropertyFilter
export type MarketingAnalyticsAggregatedQueryApi = MarketingAnalyticsAggregatedQuery
export type MarketingAnalyticsAggregatedQueryResponseApi = MarketingAnalyticsAggregatedQueryResponse
export type MarketingAnalyticsItemApi = MarketingAnalyticsItem
export type MarketingAnalyticsTableQueryApi = MarketingAnalyticsTableQuery
export type MarketingAnalyticsTableQueryResponseApi = MarketingAnalyticsTableQueryResponse
export type NonIntegratedConversionsTableQueryApi = NonIntegratedConversionsTableQuery
export type NonIntegratedConversionsTableQueryResponseApi = NonIntegratedConversionsTableQueryResponse
export type PathCleaningFilterApi = PathCleaningFilter
export type PathsFilterApi = PathsFilter
export type PathsLinkApi = PathsLink
export type PathsQueryApi = PathsQuery
export type PathsQueryResponseApi = PathsQueryResponse
export type PersonPropertyFilterApi = PersonPropertyFilter
export type PersonsNodeApi = PersonsNode
export type PropertyGroupFilterApi = PropertyGroupFilter
export type PropertyGroupFilterValueApi = PropertyGroupFilterValue
export type QueryLogTagsApi = QueryLogTags
export type QueryStatusApi = QueryStatus
export type QueryTimingApi = QueryTiming
export type RecordingPropertyFilterApi = RecordingPropertyFilter
export type ResolvedDateRangeResponseApi = ResolvedDateRangeResponse
export type ResultCustomizationByPositionApi = ResultCustomizationByPosition
export type ResultCustomizationByValueApi = ResultCustomizationByValue
export type RetentionEntityApi = RetentionEntity
export type RetentionFilterApi = RetentionFilter
export type RetentionQueryApi = RetentionQuery
export type RetentionQueryResponseApi = RetentionQueryResponse
export type RetentionResultApi = RetentionResult
export type RetentionValueApi = RetentionValue
export type RevenueAnalyticsBreakdownApi = RevenueAnalyticsBreakdown
export type RevenueAnalyticsGrossRevenueQueryApi = RevenueAnalyticsGrossRevenueQuery
export type RevenueAnalyticsGrossRevenueQueryResponseApi = RevenueAnalyticsGrossRevenueQueryResponse
export type RevenueAnalyticsMRRQueryApi = RevenueAnalyticsMRRQuery
export type RevenueAnalyticsMRRQueryResponseApi = RevenueAnalyticsMRRQueryResponse
export type RevenueAnalyticsMRRQueryResultItemApi = RevenueAnalyticsMRRQueryResultItem
export type RevenueAnalyticsMetricsQueryApi = RevenueAnalyticsMetricsQuery
export type RevenueAnalyticsMetricsQueryResponseApi = RevenueAnalyticsMetricsQueryResponse
export type RevenueAnalyticsOverviewItemApi = RevenueAnalyticsOverviewItem
export type RevenueAnalyticsOverviewQueryApi = RevenueAnalyticsOverviewQuery
export type RevenueAnalyticsOverviewQueryResponseApi = RevenueAnalyticsOverviewQueryResponse
export type RevenueAnalyticsPropertyFilterApi = RevenueAnalyticsPropertyFilter
export type RevenueAnalyticsTopCustomersQueryApi = RevenueAnalyticsTopCustomersQuery
export type RevenueAnalyticsTopCustomersQueryResponseApi = RevenueAnalyticsTopCustomersQueryResponse
export type RevenueCurrencyPropertyConfigApi = RevenueCurrencyPropertyConfig
export type RevenueExampleDataWarehouseTablesQueryApi = RevenueExampleDataWarehouseTablesQuery
export type RevenueExampleDataWarehouseTablesQueryResponseApi = RevenueExampleDataWarehouseTablesQueryResponse
export type RevenueExampleEventsQueryApi = RevenueExampleEventsQuery
export type RevenueExampleEventsQueryResponseApi = RevenueExampleEventsQueryResponse
export type SamplingRateApi = SamplingRate
export type SessionAttributionExplorerQueryApi = SessionAttributionExplorerQuery
export type SessionAttributionExplorerQueryResponseApi = SessionAttributionExplorerQueryResponse
export type SessionDataApi = SessionData
export type SessionPropertyFilterApi = SessionPropertyFilter
export type SessionsQueryApi = SessionsQuery
export type SessionsQueryResponseApi = SessionsQueryResponse
export type SpanPropertyFilterApi = SpanPropertyFilter
export type StickinessActorsQueryApi = StickinessActorsQuery
export type StickinessCriteriaApi = StickinessCriteria
export type StickinessFilterApi = StickinessFilter
export type StickinessQueryApi = StickinessQuery
export type StickinessQueryResponseApi = StickinessQueryResponse
export type TableSettingsApi = TableSettings
export type TraceQueryApi = TraceQuery
export type TraceQueryResponseApi = TraceQueryResponse
export type TracesQueryApi = TracesQuery
export type TracesQueryResponseApi = TracesQueryResponse
export type TrendsFilterApi = TrendsFilter
export type TrendsFormulaNodeApi = TrendsFormulaNode
export type TrendsQueryApi = TrendsQuery
export type TrendsQueryResponseApi = TrendsQueryResponse
export type VizSpecificOptionsApi = VizSpecificOptions
export type WebAnalyticsSamplingApi = WebAnalyticsSampling
export type WebExternalClicksTableQueryApi = WebExternalClicksTableQuery
export type WebExternalClicksTableQueryResponseApi = WebExternalClicksTableQueryResponse
export type WebGoalsQueryApi = WebGoalsQuery
export type WebGoalsQueryResponseApi = WebGoalsQueryResponse
export type WebOverviewItemApi = WebOverviewItem
export type WebOverviewQueryApi = WebOverviewQuery
export type WebOverviewQueryResponseApi = WebOverviewQueryResponse
export type WebStatsTableQueryApi = WebStatsTableQuery
export type WebStatsTableQueryResponseApi = WebStatsTableQueryResponse
export type WebVitalsPathBreakdownQueryApi = WebVitalsPathBreakdownQuery
export type WebVitalsPathBreakdownQueryResponseApi = WebVitalsPathBreakdownQueryResponse
export type WebVitalsPathBreakdownResultApi = WebVitalsPathBreakdownResult
export type WebVitalsPathBreakdownResultItemApi = WebVitalsPathBreakdownResultItem
export type WebVitalsQueryApi = WebVitalsQuery
export type WorkflowVariablePropertyFilterApi = WorkflowVariablePropertyFilter
export type YAxisSettingsApi = YAxisSettings

/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

/**
 * * `team` - Only team
 * * `global` - Global
 * * `feature_flag` - Feature Flag
 */
export type DashboardTemplateScopeEnumApi =
    (typeof DashboardTemplateScopeEnumApi)[keyof typeof DashboardTemplateScopeEnumApi]

export const DashboardTemplateScopeEnumApi = {
    Team: 'team',
    Global: 'global',
    FeatureFlag: 'feature_flag',
} as const

export interface DashboardTemplateApi {
    readonly id: string
    /**
     * @maxLength 400
     * @nullable
     */
    template_name?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    dashboard_description?: string | null
    dashboard_filters?: unknown
    /**
     * @nullable
     * @items.maxLength 255
     */
    tags?: string[] | null
    tiles?: unknown
    variables?: unknown
    /** @nullable */
    deleted?: boolean | null
    /** @nullable */
    readonly created_at: string | null
    readonly created_by: UserBasicApi
    /**
     * @maxLength 8201
     * @nullable
     */
    image_url?: string | null
    /** @nullable */
    readonly team_id: number | null
    scope?: DashboardTemplateScopeEnumApi | BlankEnumApi | null
    /**
     * @nullable
     * @items.maxLength 255
     */
    availability_contexts?: string[] | null
    /** Manually curated; used to highlight templates in the UI. */
    is_featured?: boolean
}

export interface PaginatedDashboardTemplateListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DashboardTemplateApi[]
}

export interface PatchedDashboardTemplateApi {
    readonly id?: string
    /**
     * @maxLength 400
     * @nullable
     */
    template_name?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    dashboard_description?: string | null
    dashboard_filters?: unknown
    /**
     * @nullable
     * @items.maxLength 255
     */
    tags?: string[] | null
    tiles?: unknown
    variables?: unknown
    /** @nullable */
    deleted?: boolean | null
    /** @nullable */
    readonly created_at?: string | null
    readonly created_by?: UserBasicApi
    /**
     * @maxLength 8201
     * @nullable
     */
    image_url?: string | null
    /** @nullable */
    readonly team_id?: number | null
    scope?: DashboardTemplateScopeEnumApi | BlankEnumApi | null
    /**
     * @nullable
     * @items.maxLength 255
     */
    availability_contexts?: string[] | null
    /** Manually curated; used to highlight templates in the UI. */
    is_featured?: boolean
}

export interface CopyDashboardTemplateApi {
    /** UUID of a team-scoped template in the same organization. Global and feature-flag templates cannot be copied with this endpoint. */
    source_template_id: string
}

/**
 * * `default` - Default
 * * `template` - Template
 * * `duplicate` - Duplicate
 * * `unlisted` - Unlisted (product-embedded)
 */
export type CreationModeEnumApi = (typeof CreationModeEnumApi)[keyof typeof CreationModeEnumApi]

export const CreationModeEnumApi = {
    Default: 'default',
    Template: 'template',
    Duplicate: 'duplicate',
    Unlisted: 'unlisted',
} as const

/**
 * * `21` - Everyone in the project can edit
 * * `37` - Only those invited to this dashboard can edit
 */
export type RestrictionLevelEnumApi = (typeof RestrictionLevelEnumApi)[keyof typeof RestrictionLevelEnumApi]

export const RestrictionLevelEnumApi = {
    Number21: 21,
    Number37: 37,
} as const

export type EffectivePrivilegeLevelEnumApi =
    (typeof EffectivePrivilegeLevelEnumApi)[keyof typeof EffectivePrivilegeLevelEnumApi]

export const EffectivePrivilegeLevelEnumApi = {
    Number21: 21,
    Number37: 37,
} as const

export type SearchMatchTypeEnumApi = (typeof SearchMatchTypeEnumApi)[keyof typeof SearchMatchTypeEnumApi]

export const SearchMatchTypeEnumApi = {
    Exact: 'exact',
    Similar: 'similar',
} as const

/**
 * Serializer mixin that handles tags for objects.
 */
export interface DashboardBasicApi {
    readonly id: number
    /**
     * Name of the dashboard.
     * @nullable
     */
    readonly name: string | null
    /** Description of the dashboard. */
    readonly description: string
    /** Whether the dashboard is pinned to the top of the list. */
    readonly pinned: boolean
    readonly created_at: string
    readonly created_by: UserBasicApi
    /** @nullable */
    readonly last_accessed_at: string | null
    /** @nullable */
    readonly last_viewed_at: string | null
    readonly is_shared: boolean
    readonly deleted: boolean
    readonly creation_mode: CreationModeEnumApi
    tags?: unknown[]
    /** Controls who can edit the dashboard.
     *
     * * `21` - Everyone in the project can edit
     * * `37` - Only those invited to this dashboard can edit */
    readonly restriction_level: RestrictionLevelEnumApi
    readonly effective_restriction_level: EffectivePrivilegeLevelEnumApi
    readonly effective_privilege_level: EffectivePrivilegeLevelEnumApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    readonly access_control_version: string
    /** @nullable */
    readonly last_refresh: string | null
    readonly team_id: number
    /** How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match only). Results are ordered exact-first. Null when the list is not filtered by `search`. */
    readonly search_match_type: SearchMatchTypeEnumApi | null
}

export interface PaginatedDashboardBasicListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DashboardBasicApi[]
}

export type DashboardApiFilters = { [key: string]: unknown }

/**
 * @nullable
 */
export type DashboardApiVariables = { [key: string]: unknown } | null

/**
 * @nullable
 */
export type DashboardApiPersistedFilters = { [key: string]: unknown } | null

/**
 * @nullable
 */
export type DashboardApiPersistedVariables = { [key: string]: unknown } | null

export type DashboardApiTilesItem = { [key: string]: unknown }

/**
 * Serializer mixin that handles tags for objects.
 */
export interface DashboardApi {
    readonly id: number
    /**
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    description?: string
    pinned?: boolean
    readonly created_at: string
    readonly created_by: UserBasicApi
    /** @nullable */
    last_accessed_at?: string | null
    /** @nullable */
    readonly last_viewed_at: string | null
    readonly is_shared: boolean
    deleted?: boolean
    readonly creation_mode: CreationModeEnumApi
    readonly filters: DashboardApiFilters
    /** @nullable */
    readonly variables: DashboardApiVariables
    /** Custom color mapping for breakdown values. */
    breakdown_colors?: unknown
    /**
     * ID of the color theme used for chart visualizations.
     * @nullable
     */
    data_color_theme_id?: number | null
    tags?: unknown[]
    restriction_level?: RestrictionLevelEnumApi
    readonly effective_restriction_level: EffectivePrivilegeLevelEnumApi
    readonly effective_privilege_level: EffectivePrivilegeLevelEnumApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    readonly access_control_version: string
    /** @nullable */
    last_refresh?: string | null
    /** @nullable */
    readonly persisted_filters: DashboardApiPersistedFilters
    /** @nullable */
    readonly persisted_variables: DashboardApiPersistedVariables
    readonly team_id: number
    /**
     * List of quick filter IDs associated with this dashboard
     * @nullable
     */
    quick_filter_ids?: string[] | null
    /** @nullable */
    readonly tiles: readonly DashboardApiTilesItem[] | null
    /** Template key to create the dashboard from a predefined template. */
    use_template?: string
    /**
     * ID of an existing dashboard to duplicate.
     * @nullable
     */
    use_dashboard?: number | null
    /** When deleting, also delete insights that are only on this dashboard. */
    delete_insights?: boolean
    _create_in_folder?: string
}

export interface DashboardCollaboratorApi {
    readonly id: string
    readonly dashboard_id: number
    readonly user: UserBasicApi
    level: RestrictionLevelEnumApi
    readonly added_at: string
    readonly updated_at: string
    user_uuid: string
}

/**
 * * `error_tracking_list` - error_tracking_list
 * * `session_replay_list` - session_replay_list
 */
export type DashboardPatchWidgetOpenApiWidgetTypeEnumApi =
    (typeof DashboardPatchWidgetOpenApiWidgetTypeEnumApi)[keyof typeof DashboardPatchWidgetOpenApiWidgetTypeEnumApi]

export const DashboardPatchWidgetOpenApiWidgetTypeEnumApi = {
    ErrorTrackingList: 'error_tracking_list',
    SessionReplayList: 'session_replay_list',
} as const

export type WidgetDateRangeApiDateFrom =
    | (typeof WidgetDateRangeApiDateFrom)[keyof typeof WidgetDateRangeApiDateFrom]
    | null

export const WidgetDateRangeApiDateFrom = {
    '1h': '-1h',
    '3h': '-3h',
    '24h': '-24h',
    '7d': '-7d',
    '14d': '-14d',
    '30d': '-30d',
    '90d': '-90d',
} as const

export interface WidgetDateRangeApi {
    date_from?: WidgetDateRangeApiDateFrom
}

export type PropertyOperatorApi = (typeof PropertyOperatorApi)[keyof typeof PropertyOperatorApi]

export const PropertyOperatorApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    Regex: 'regex',
    NotRegex: 'not_regex',
    Gt: 'gt',
    Gte: 'gte',
    Lt: 'lt',
    Lte: 'lte',
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
    IsDateExact: 'is_date_exact',
    IsDateBefore: 'is_date_before',
    IsDateAfter: 'is_date_after',
    Between: 'between',
    NotBetween: 'not_between',
    Min: 'min',
    Max: 'max',
    In: 'in',
    NotIn: 'not_in',
    IsCleanedPathExact: 'is_cleaned_path_exact',
    FlagEvaluatesTo: 'flag_evaluates_to',
    SemverEq: 'semver_eq',
    SemverNeq: 'semver_neq',
    SemverGt: 'semver_gt',
    SemverGte: 'semver_gte',
    SemverLt: 'semver_lt',
    SemverLte: 'semver_lte',
    SemverTilde: 'semver_tilde',
    SemverCaret: 'semver_caret',
    SemverWildcard: 'semver_wildcard',
    IcontainsMulti: 'icontains_multi',
    NotIcontainsMulti: 'not_icontains_multi',
} as const

export interface WidgetFilterEntryApi {
    /** @minLength 1 */
    filterId: string
    /** @minLength 1 */
    propertyName: string
    /** @minLength 1 */
    optionId: string
    operator: PropertyOperatorApi
    value?: string | string[] | null
}

/**
 * Issue ranking column.
 */
export type ErrorTrackingListWidgetConfigApiOrderBy =
    (typeof ErrorTrackingListWidgetConfigApiOrderBy)[keyof typeof ErrorTrackingListWidgetConfigApiOrderBy]

export const ErrorTrackingListWidgetConfigApiOrderBy = {
    LastSeen: 'last_seen',
    FirstSeen: 'first_seen',
    Occurrences: 'occurrences',
    Users: 'users',
    Sessions: 'sessions',
} as const

/**
 * Sort direction for orderBy.
 */
export type ErrorTrackingListWidgetConfigApiOrderDirection =
    (typeof ErrorTrackingListWidgetConfigApiOrderDirection)[keyof typeof ErrorTrackingListWidgetConfigApiOrderDirection]

export const ErrorTrackingListWidgetConfigApiOrderDirection = {
    Asc: 'ASC',
    Desc: 'DESC',
} as const

/**
 * Issue status filter.
 */
export type ErrorTrackingListWidgetConfigApiStatus =
    (typeof ErrorTrackingListWidgetConfigApiStatus)[keyof typeof ErrorTrackingListWidgetConfigApiStatus]

export const ErrorTrackingListWidgetConfigApiStatus = {
    Archived: 'archived',
    Active: 'active',
    Resolved: 'resolved',
    PendingRelease: 'pending_release',
    Suppressed: 'suppressed',
    All: 'all',
} as const

export type WidgetAssigneeFilterApiType = (typeof WidgetAssigneeFilterApiType)[keyof typeof WidgetAssigneeFilterApiType]

export const WidgetAssigneeFilterApiType = {
    User: 'user',
    Role: 'role',
} as const

export interface WidgetAssigneeFilterApi {
    id: string | number
    type: WidgetAssigneeFilterApiType
}

export type ErrorTrackingListWidgetConfigApiWidgetFilters = { [key: string]: WidgetFilterEntryApi } | null

export interface ErrorTrackingListWidgetConfigApi {
    dateRange?: WidgetDateRangeApi | null
    filterTestAccounts?: boolean | null
    widgetFilters?: ErrorTrackingListWidgetConfigApiWidgetFilters
    /**
     * Maximum number of issues to return.
     * @minimum 1
     * @maximum 25
     */
    limit?: number
    /** Issue ranking column. */
    orderBy?: ErrorTrackingListWidgetConfigApiOrderBy
    /** Sort direction for orderBy. */
    orderDirection?: ErrorTrackingListWidgetConfigApiOrderDirection
    /** Issue status filter. */
    status?: ErrorTrackingListWidgetConfigApiStatus
    /** Filter by assignee ({type: user|role, id}). Omit for any assignee. */
    assignee?: WidgetAssigneeFilterApi | null
}

/**
 * Recording ranking column.
 */
export type SessionReplayListWidgetConfigApiOrderBy =
    (typeof SessionReplayListWidgetConfigApiOrderBy)[keyof typeof SessionReplayListWidgetConfigApiOrderBy]

export const SessionReplayListWidgetConfigApiOrderBy = {
    StartTime: 'start_time',
    ActivityScore: 'activity_score',
    RecordingDuration: 'recording_duration',
    Duration: 'duration',
    ClickCount: 'click_count',
    ConsoleErrorCount: 'console_error_count',
} as const

/**
 * Sort direction for orderBy.
 */
export type SessionReplayListWidgetConfigApiOrderDirection =
    (typeof SessionReplayListWidgetConfigApiOrderDirection)[keyof typeof SessionReplayListWidgetConfigApiOrderDirection]

export const SessionReplayListWidgetConfigApiOrderDirection = {
    Asc: 'ASC',
    Desc: 'DESC',
} as const

export type SessionReplayListWidgetConfigApiWidgetFilters = { [key: string]: WidgetFilterEntryApi } | null

export interface SessionReplayListWidgetConfigApi {
    dateRange?: WidgetDateRangeApi | null
    filterTestAccounts?: boolean | null
    widgetFilters?: SessionReplayListWidgetConfigApiWidgetFilters
    /**
     * Maximum number of recordings to return.
     * @minimum 1
     * @maximum 25
     */
    limit?: number
    /** Recording ranking column. */
    orderBy?: SessionReplayListWidgetConfigApiOrderBy
    /** Sort direction for orderBy. */
    orderDirection?: SessionReplayListWidgetConfigApiOrderDirection
}

export type DashboardWidgetConfigApi = ErrorTrackingListWidgetConfigApi | SessionReplayListWidgetConfigApi

export interface DashboardPatchWidgetOpenApiApi {
    /** Existing widget row ID when updating a widget tile via dashboard PATCH. */
    id?: string
    /** Widget type identifier (cannot be changed on update).
     *
     * * `error_tracking_list` - error_tracking_list
     * * `session_replay_list` - session_replay_list */
    widget_type?: DashboardPatchWidgetOpenApiWidgetTypeEnumApi
    /** Widget-specific configuration. Shape depends on the tile's widget_type. */
    config?: DashboardWidgetConfigApi
    /**
     * Optional custom display name for the widget tile.
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /** Optional markdown description shown when show_description is enabled. */
    description?: string
}

export interface DashboardPatchTileOpenApiApi {
    /** Dashboard tile ID to update. */
    id?: number
    /** Nested widget row updates. */
    widget?: DashboardPatchWidgetOpenApiApi
}

/**
 * OpenAPI-only PATCH body for dashboards (agents/MCP).
 *
 * Must be a superset of ``dashboard_patch_runtime_openapi_field_names()`` — ``extend_schema(request=...)``
 * replaces the inferred schema entirely. Contract: ``test_dashboard_openapi.py``.
 */
export interface PatchedPatchedDashboardOpenApiApi {
    /**
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    description?: string
    pinned?: boolean
    /** Custom color mapping for breakdown values. */
    breakdown_colors?: unknown
    /**
     * ID of the color theme used for chart visualizations.
     * @nullable
     */
    data_color_theme_id?: number | null
    tags?: string[]
    restriction_level?: EffectivePrivilegeLevelEnumApi
    /**
     * List of quick filter IDs associated with this dashboard.
     * @nullable
     */
    quick_filter_ids?: string[] | null
    /** Dashboard tiles to update. Widget tiles accept nested widget.config patches. */
    tiles?: DashboardPatchTileOpenApiApi[]
    /** Template key to create the dashboard from a predefined template. */
    use_template?: string
    /**
     * ID of an existing dashboard to duplicate.
     * @nullable
     */
    use_dashboard?: number | null
    /** When deleting, also delete insights that are only on this dashboard. */
    delete_insights?: boolean
}

export interface CopyDashboardTileRequestApi {
    /** Dashboard id the tile currently belongs to. */
    fromDashboardId: number
    /** Dashboard tile id to copy. */
    tileId: number
}

export interface TileLayoutBoxApi {
    /** Column position in the dashboard grid (0-indexed). */
    x?: number
    /** Row position in the dashboard grid (0-indexed). */
    y?: number
    /** Width in grid columns. The desktop grid is 12 columns wide. */
    w?: number
    /** Height in grid rows. */
    h?: number
}

export interface TileLayoutsApi {
    /** Layout for the standard (desktop) breakpoint. The grid is 12 columns wide. */
    sm?: TileLayoutBoxApi
    /** Layout for the small (mobile) breakpoint. The grid is 1 column wide. */
    xs?: TileLayoutBoxApi
}

export interface CreateTextTileRequestApi {
    /**
     * Markdown body for the text tile. Supports headings, lists, and inline formatting. Useful as a dashboard section heading, divider, or annotation between insights. Max 4000 characters.
     * @minLength 1
     * @maxLength 4000
     */
    body: string
    /** Optional grid layout per breakpoint. If omitted, the tile is placed at the bottom of the dashboard using the default size. Text tiles typically use a thin full-width banner (e.g. w=12, h=1). */
    layouts?: TileLayoutsApi
    /**
     * Optional accent color name (e.g. 'blue', 'green', 'purple', 'black').
     * @maxLength 400
     * @nullable
     */
    color?: string | null
}

export type InsightVizNodeApiKind = (typeof InsightVizNodeApiKind)[keyof typeof InsightVizNodeApiKind]

export const InsightVizNodeApiKind = {
    InsightVizNode: 'InsightVizNode',
} as const

export type BreakdownTypeApi = (typeof BreakdownTypeApi)[keyof typeof BreakdownTypeApi]

export const BreakdownTypeApi = {
    Cohort: 'cohort',
    Person: 'person',
    Event: 'event',
    EventMetadata: 'event_metadata',
    Group: 'group',
    Session: 'session',
    Hogql: 'hogql',
    DataWarehouse: 'data_warehouse',
    DataWarehousePersonProperty: 'data_warehouse_person_property',
    RevenueAnalytics: 'revenue_analytics',
} as const

export type MultipleBreakdownTypeApi = (typeof MultipleBreakdownTypeApi)[keyof typeof MultipleBreakdownTypeApi]

export const MultipleBreakdownTypeApi = {
    Person: 'person',
    Event: 'event',
    EventMetadata: 'event_metadata',
    Group: 'group',
    Session: 'session',
    Hogql: 'hogql',
    Cohort: 'cohort',
    RevenueAnalytics: 'revenue_analytics',
    DataWarehouse: 'data_warehouse',
    DataWarehousePersonProperty: 'data_warehouse_person_property',
} as const

export type IntervalTypeApi = (typeof IntervalTypeApi)[keyof typeof IntervalTypeApi]

export const IntervalTypeApi = {
    Second: 'second',
    Minute: 'minute',
    Hour: 'hour',
    Day: 'day',
    Week: 'week',
    Month: 'month',
} as const

export type BounceRatePageViewModeApi = (typeof BounceRatePageViewModeApi)[keyof typeof BounceRatePageViewModeApi]

export const BounceRatePageViewModeApi = {
    CountPageviews: 'count_pageviews',
    UniqUrls: 'uniq_urls',
    UniqPageScreenAutocaptures: 'uniq_page_screen_autocaptures',
} as const

export type FilterLogicalOperatorApi = (typeof FilterLogicalOperatorApi)[keyof typeof FilterLogicalOperatorApi]

export const FilterLogicalOperatorApi = {
    And: 'AND',
    Or: 'OR',
} as const

export type CustomChannelFieldApi = (typeof CustomChannelFieldApi)[keyof typeof CustomChannelFieldApi]

export const CustomChannelFieldApi = {
    UtmSource: 'utm_source',
    UtmMedium: 'utm_medium',
    UtmCampaign: 'utm_campaign',
    ReferringDomain: 'referring_domain',
    Url: 'url',
    Pathname: 'pathname',
    Hostname: 'hostname',
} as const

export type CustomChannelOperatorApi = (typeof CustomChannelOperatorApi)[keyof typeof CustomChannelOperatorApi]

export const CustomChannelOperatorApi = {
    Exact: 'exact',
    IsNot: 'is_not',
    IsSet: 'is_set',
    IsNotSet: 'is_not_set',
    Icontains: 'icontains',
    NotIcontains: 'not_icontains',
    Regex: 'regex',
    NotRegex: 'not_regex',
} as const

export type InCohortViaApi = (typeof InCohortViaApi)[keyof typeof InCohortViaApi]

export const InCohortViaApi = {
    Auto: 'auto',
    Leftjoin: 'leftjoin',
    Subquery: 'subquery',
    LeftjoinConjoined: 'leftjoin_conjoined',
} as const

export type InlineCohortCalculationApi = (typeof InlineCohortCalculationApi)[keyof typeof InlineCohortCalculationApi]

export const InlineCohortCalculationApi = {
    Off: 'off',
    Auto: 'auto',
    Always: 'always',
} as const

export type MaterializationModeApi = (typeof MaterializationModeApi)[keyof typeof MaterializationModeApi]

export const MaterializationModeApi = {
    Auto: 'auto',
    LegacyNullAsString: 'legacy_null_as_string',
    LegacyNullAsNull: 'legacy_null_as_null',
    Disabled: 'disabled',
} as const

export type MaterializedColumnsOptimizationModeApi =
    (typeof MaterializedColumnsOptimizationModeApi)[keyof typeof MaterializedColumnsOptimizationModeApi]

export const MaterializedColumnsOptimizationModeApi = {
    Disabled: 'disabled',
    Optimized: 'optimized',
} as const

export type ParserModeApi = (typeof ParserModeApi)[keyof typeof ParserModeApi]

export const ParserModeApi = {
    CppOnly: 'cpp_only',
    CppWithRustShadow: 'cpp_with_rust_shadow',
    CppWithRustPyShadow: 'cpp_with_rust_py_shadow',
    RustWithCppShadow: 'rust_with_cpp_shadow',
    RustOnly: 'rust_only',
    RustPyOnly: 'rust_py_only',
    RustPyWithCppShadow: 'rust_py_with_cpp_shadow',
} as const

export type PersonsArgMaxVersionApi = (typeof PersonsArgMaxVersionApi)[keyof typeof PersonsArgMaxVersionApi]

export const PersonsArgMaxVersionApi = {
    Auto: 'auto',
    V1: 'v1',
    V2: 'v2',
} as const

export type PersonsJoinModeApi = (typeof PersonsJoinModeApi)[keyof typeof PersonsJoinModeApi]

export const PersonsJoinModeApi = {
    Inner: 'inner',
    Left: 'left',
} as const

export type PersonsOnEventsModeApi = (typeof PersonsOnEventsModeApi)[keyof typeof PersonsOnEventsModeApi]

export const PersonsOnEventsModeApi = {
    Disabled: 'disabled',
    PersonIdNoOverridePropertiesOnEvents: 'person_id_no_override_properties_on_events',
    PersonIdOverridePropertiesOnEvents: 'person_id_override_properties_on_events',
    PersonIdOverridePropertiesJoined: 'person_id_override_properties_joined',
} as const

export type PropertyGroupsModeApi = (typeof PropertyGroupsModeApi)[keyof typeof PropertyGroupsModeApi]

export const PropertyGroupsModeApi = {
    Enabled: 'enabled',
    Disabled: 'disabled',
    Optimized: 'optimized',
} as const

export type SessionTableVersionApi = (typeof SessionTableVersionApi)[keyof typeof SessionTableVersionApi]

export const SessionTableVersionApi = {
    Auto: 'auto',
    V1: 'v1',
    V2: 'v2',
    V3: 'v3',
} as const

export type SessionsV2JoinModeApi = (typeof SessionsV2JoinModeApi)[keyof typeof SessionsV2JoinModeApi]

export const SessionsV2JoinModeApi = {
    String: 'string',
    Uuid: 'uuid',
} as const

export type Key10Api = (typeof Key10Api)[keyof typeof Key10Api]

export const Key10Api = {
    TagName: 'tag_name',
    Text: 'text',
    Href: 'href',
    Selector: 'selector',
} as const

export type DurationTypeApi = (typeof DurationTypeApi)[keyof typeof DurationTypeApi]

export const DurationTypeApi = {
    Duration: 'duration',
    ActiveSeconds: 'active_seconds',
    InactiveSeconds: 'inactive_seconds',
} as const

export type GroupPropertyFilterApiGroupKeyNames = { [key: string]: string } | null

export const EmptyPropertyFilterApiValue = {
    type: 'empty',
} as const
export type LogPropertyFilterTypeApi = (typeof LogPropertyFilterTypeApi)[keyof typeof LogPropertyFilterTypeApi]

export const LogPropertyFilterTypeApi = {
    Log: 'log',
    LogAttribute: 'log_attribute',
    LogResourceAttribute: 'log_resource_attribute',
} as const

export type SpanPropertyFilterTypeApi = (typeof SpanPropertyFilterTypeApi)[keyof typeof SpanPropertyFilterTypeApi]

export const SpanPropertyFilterTypeApi = {
    Span: 'span',
    SpanAttribute: 'span_attribute',
    SpanResourceAttribute: 'span_resource_attribute',
} as const

export type TrendsQueryResponseApiResultsItem = { [key: string]: unknown }

export type BaseMathTypeApi = (typeof BaseMathTypeApi)[keyof typeof BaseMathTypeApi]

export const BaseMathTypeApi = {
    Total: 'total',
    Dau: 'dau',
    WeeklyActive: 'weekly_active',
    MonthlyActive: 'monthly_active',
    UniqueSession: 'unique_session',
    FirstTimeForUser: 'first_time_for_user',
    FirstMatchingEventForUser: 'first_matching_event_for_user',
} as const

export type FunnelMathTypeApi = (typeof FunnelMathTypeApi)[keyof typeof FunnelMathTypeApi]

export const FunnelMathTypeApi = {
    Total: 'total',
    FirstTimeForUser: 'first_time_for_user',
    FirstTimeForUserWithFilters: 'first_time_for_user_with_filters',
} as const

export type PropertyMathTypeApi = (typeof PropertyMathTypeApi)[keyof typeof PropertyMathTypeApi]

export const PropertyMathTypeApi = {
    Avg: 'avg',
    Sum: 'sum',
    Min: 'min',
    Max: 'max',
    Median: 'median',
    P75: 'p75',
    P90: 'p90',
    P95: 'p95',
    P99: 'p99',
} as const

export type CountPerActorMathTypeApi = (typeof CountPerActorMathTypeApi)[keyof typeof CountPerActorMathTypeApi]

export const CountPerActorMathTypeApi = {
    AvgCountPerActor: 'avg_count_per_actor',
    MinCountPerActor: 'min_count_per_actor',
    MaxCountPerActor: 'max_count_per_actor',
    MedianCountPerActor: 'median_count_per_actor',
    P75CountPerActor: 'p75_count_per_actor',
    P90CountPerActor: 'p90_count_per_actor',
    P95CountPerActor: 'p95_count_per_actor',
    P99CountPerActor: 'p99_count_per_actor',
} as const

export type ExperimentMetricMathTypeApi = (typeof ExperimentMetricMathTypeApi)[keyof typeof ExperimentMetricMathTypeApi]

export const ExperimentMetricMathTypeApi = {
    Total: 'total',
    Sum: 'sum',
    UniqueSession: 'unique_session',
    Min: 'min',
    Max: 'max',
    Avg: 'avg',
    Dau: 'dau',
    UniqueGroup: 'unique_group',
    Hogql: 'hogql',
} as const

export type CalendarHeatmapMathTypeApi = (typeof CalendarHeatmapMathTypeApi)[keyof typeof CalendarHeatmapMathTypeApi]

export const CalendarHeatmapMathTypeApi = {
    Total: 'total',
    Dau: 'dau',
} as const

export type MathGroupTypeIndexApi = (typeof MathGroupTypeIndexApi)[keyof typeof MathGroupTypeIndexApi]

export const MathGroupTypeIndexApi = {
    Number0: 0,
    Number1: 1,
    Number2: 2,
    Number3: 3,
    Number4: 4,
} as const

export type CurrencyCodeApi = (typeof CurrencyCodeApi)[keyof typeof CurrencyCodeApi]

export const CurrencyCodeApi = {
    Aed: 'AED',
    Afn: 'AFN',
    All: 'ALL',
    Amd: 'AMD',
    Ang: 'ANG',
    Aoa: 'AOA',
    Ars: 'ARS',
    Aud: 'AUD',
    Awg: 'AWG',
    Azn: 'AZN',
    Bam: 'BAM',
    Bbd: 'BBD',
    Bdt: 'BDT',
    Bgn: 'BGN',
    Bhd: 'BHD',
    Bif: 'BIF',
    Bmd: 'BMD',
    Bnd: 'BND',
    Bob: 'BOB',
    Brl: 'BRL',
    Bsd: 'BSD',
    Btc: 'BTC',
    Btn: 'BTN',
    Bwp: 'BWP',
    Byn: 'BYN',
    Bzd: 'BZD',
    Cad: 'CAD',
    Cdf: 'CDF',
    Chf: 'CHF',
    Clp: 'CLP',
    Cny: 'CNY',
    Cop: 'COP',
    Crc: 'CRC',
    Cve: 'CVE',
    Czk: 'CZK',
    Djf: 'DJF',
    Dkk: 'DKK',
    Dop: 'DOP',
    Dzd: 'DZD',
    Egp: 'EGP',
    Ern: 'ERN',
    Etb: 'ETB',
    Eur: 'EUR',
    Fjd: 'FJD',
    Gbp: 'GBP',
    Gel: 'GEL',
    Ghs: 'GHS',
    Gip: 'GIP',
    Gmd: 'GMD',
    Gnf: 'GNF',
    Gtq: 'GTQ',
    Gyd: 'GYD',
    Hkd: 'HKD',
    Hnl: 'HNL',
    Hrk: 'HRK',
    Htg: 'HTG',
    Huf: 'HUF',
    Idr: 'IDR',
    Ils: 'ILS',
    Inr: 'INR',
    Iqd: 'IQD',
    Irr: 'IRR',
    Isk: 'ISK',
    Jmd: 'JMD',
    Jod: 'JOD',
    Jpy: 'JPY',
    Kes: 'KES',
    Kgs: 'KGS',
    Khr: 'KHR',
    Kmf: 'KMF',
    Krw: 'KRW',
    Kwd: 'KWD',
    Kyd: 'KYD',
    Kzt: 'KZT',
    Lak: 'LAK',
    Lbp: 'LBP',
    Lkr: 'LKR',
    Lrd: 'LRD',
    Ltl: 'LTL',
    Lvl: 'LVL',
    Lsl: 'LSL',
    Lyd: 'LYD',
    Mad: 'MAD',
    Mdl: 'MDL',
    Mga: 'MGA',
    Mkd: 'MKD',
    Mmk: 'MMK',
    Mnt: 'MNT',
    Mop: 'MOP',
    Mru: 'MRU',
    Mtl: 'MTL',
    Mur: 'MUR',
    Mvr: 'MVR',
    Mwk: 'MWK',
    Mxn: 'MXN',
    Myr: 'MYR',
    Mzn: 'MZN',
    Nad: 'NAD',
    Ngn: 'NGN',
    Nio: 'NIO',
    Nok: 'NOK',
    Npr: 'NPR',
    Nzd: 'NZD',
    Omr: 'OMR',
    Pab: 'PAB',
    Pen: 'PEN',
    Pgk: 'PGK',
    Php: 'PHP',
    Pkr: 'PKR',
    Pln: 'PLN',
    Pyg: 'PYG',
    Qar: 'QAR',
    Ron: 'RON',
    Rsd: 'RSD',
    Rub: 'RUB',
    Rwf: 'RWF',
    Sar: 'SAR',
    Sbd: 'SBD',
    Scr: 'SCR',
    Sdg: 'SDG',
    Sek: 'SEK',
    Sgd: 'SGD',
    Srd: 'SRD',
    Ssp: 'SSP',
    Stn: 'STN',
    Syp: 'SYP',
    Szl: 'SZL',
    Thb: 'THB',
    Tjs: 'TJS',
    Tmt: 'TMT',
    Tnd: 'TND',
    Top: 'TOP',
    Try: 'TRY',
    Ttd: 'TTD',
    Twd: 'TWD',
    Tzs: 'TZS',
    Uah: 'UAH',
    Ugx: 'UGX',
    Usd: 'USD',
    Uyu: 'UYU',
    Uzs: 'UZS',
    Ves: 'VES',
    Vnd: 'VND',
    Vuv: 'VUV',
    Wst: 'WST',
    Xaf: 'XAF',
    Xcd: 'XCD',
    Xof: 'XOF',
    Xpf: 'XPF',
    Yer: 'YER',
    Zar: 'ZAR',
    Zmw: 'ZMW',
} as const

export type EventsNodeApiResponse = { [key: string]: unknown } | null

export type ActionsNodeApiResponse = { [key: string]: unknown } | null

export type DataWarehouseNodeApiResponse = { [key: string]: unknown } | null

export type GroupNodeApiResponse = { [key: string]: unknown } | null

export type AggregationAxisFormatApi = (typeof AggregationAxisFormatApi)[keyof typeof AggregationAxisFormatApi]

export const AggregationAxisFormatApi = {
    Numeric: 'numeric',
    Duration: 'duration',
    DurationMs: 'duration_ms',
    Percentage: 'percentage',
    PercentageScaled: 'percentage_scaled',
    Currency: 'currency',
    Short: 'short',
} as const

export type DetailedResultsAggregationTypeApi =
    (typeof DetailedResultsAggregationTypeApi)[keyof typeof DetailedResultsAggregationTypeApi]

export const DetailedResultsAggregationTypeApi = {
    Total: 'total',
    Average: 'average',
    Median: 'median',
} as const

export type ChartDisplayTypeApi = (typeof ChartDisplayTypeApi)[keyof typeof ChartDisplayTypeApi]

export const ChartDisplayTypeApi = {
    Auto: 'Auto',
    ActionsLineGraph: 'ActionsLineGraph',
    ActionsBar: 'ActionsBar',
    ActionsUnstackedBar: 'ActionsUnstackedBar',
    ActionsStackedBar: 'ActionsStackedBar',
    ActionsAreaGraph: 'ActionsAreaGraph',
    ActionsLineGraphCumulative: 'ActionsLineGraphCumulative',
    BoldNumber: 'BoldNumber',
    ActionsPie: 'ActionsPie',
    ActionsBarValue: 'ActionsBarValue',
    ActionsTable: 'ActionsTable',
    WorldMap: 'WorldMap',
    CalendarHeatmap: 'CalendarHeatmap',
    TwoDimensionalHeatmap: 'TwoDimensionalHeatmap',
    BoxPlot: 'BoxPlot',
} as const

export type PositionApi = (typeof PositionApi)[keyof typeof PositionApi]

export const PositionApi = {
    Start: 'start',
    End: 'end',
} as const

export type ResultCustomizationByApi = (typeof ResultCustomizationByApi)[keyof typeof ResultCustomizationByApi]

export const ResultCustomizationByApi = {
    Value: 'value',
    Position: 'position',
} as const

export type DataColorTokenApi = (typeof DataColorTokenApi)[keyof typeof DataColorTokenApi]

export const DataColorTokenApi = {
    Preset1: 'preset-1',
    Preset2: 'preset-2',
    Preset3: 'preset-3',
    Preset4: 'preset-4',
    Preset5: 'preset-5',
    Preset6: 'preset-6',
    Preset7: 'preset-7',
    Preset8: 'preset-8',
    Preset9: 'preset-9',
    Preset10: 'preset-10',
    Preset11: 'preset-11',
    Preset12: 'preset-12',
    Preset13: 'preset-13',
    Preset14: 'preset-14',
    Preset15: 'preset-15',
} as const

export type YAxisScaleTypeApi = (typeof YAxisScaleTypeApi)[keyof typeof YAxisScaleTypeApi]

export const YAxisScaleTypeApi = {
    Log10: 'log10',
    Linear: 'linear',
} as const

/**
 * Customizations for the appearance of result datasets.
 */
export type TrendsFilterApiResultCustomizations =
    | { [key: string]: ResultCustomizationByValueApi }
    | { [key: string]: ResultCustomizationByPositionApi }
    | null

export type BreakdownAttributionTypeApi = (typeof BreakdownAttributionTypeApi)[keyof typeof BreakdownAttributionTypeApi]

export const BreakdownAttributionTypeApi = {
    FirstTouch: 'first_touch',
    LastTouch: 'last_touch',
    AllEvents: 'all_events',
    Step: 'step',
} as const

export type FunnelExclusionEventsNodeApiResponse = { [key: string]: unknown } | null

export type FunnelExclusionActionsNodeApiResponse = { [key: string]: unknown } | null

export type StepOrderValueApi = (typeof StepOrderValueApi)[keyof typeof StepOrderValueApi]

export const StepOrderValueApi = {
    Strict: 'strict',
    Unordered: 'unordered',
    Ordered: 'ordered',
} as const

export type FunnelStepReferenceApi = (typeof FunnelStepReferenceApi)[keyof typeof FunnelStepReferenceApi]

export const FunnelStepReferenceApi = {
    Total: 'total',
    Previous: 'previous',
} as const

export type FunnelVizTypeApi = (typeof FunnelVizTypeApi)[keyof typeof FunnelVizTypeApi]

export const FunnelVizTypeApi = {
    Steps: 'steps',
    TimeToConvert: 'time_to_convert',
    Trends: 'trends',
    Flow: 'flow',
} as const

export type FunnelConversionWindowTimeUnitApi =
    (typeof FunnelConversionWindowTimeUnitApi)[keyof typeof FunnelConversionWindowTimeUnitApi]

export const FunnelConversionWindowTimeUnitApi = {
    Second: 'second',
    Minute: 'minute',
    Hour: 'hour',
    Day: 'day',
    Week: 'week',
    Month: 'month',
} as const

export type FunnelLayoutApi = (typeof FunnelLayoutApi)[keyof typeof FunnelLayoutApi]

export const FunnelLayoutApi = {
    Horizontal: 'horizontal',
    Vertical: 'vertical',
} as const

/**
 * Customizations for the appearance of result datasets.
 */
export type FunnelsFilterApiResultCustomizations = { [key: string]: ResultCustomizationByValueApi } | null

export type FunnelsDataWarehouseNodeApiResponse = { [key: string]: unknown } | null

export type AggregationPropertyTypeApi = (typeof AggregationPropertyTypeApi)[keyof typeof AggregationPropertyTypeApi]

export const AggregationPropertyTypeApi = {
    Event: 'event',
    Person: 'person',
    DataWarehouse: 'data_warehouse',
} as const

export type AggregationTypeApi = (typeof AggregationTypeApi)[keyof typeof AggregationTypeApi]

export const AggregationTypeApi = {
    Count: 'count',
    Sum: 'sum',
    Avg: 'avg',
} as const

export type RetentionDashboardDisplayTypeApi =
    (typeof RetentionDashboardDisplayTypeApi)[keyof typeof RetentionDashboardDisplayTypeApi]

export const RetentionDashboardDisplayTypeApi = {
    TableOnly: 'table_only',
    GraphOnly: 'graph_only',
    All: 'all',
} as const

export type MeanRetentionCalculationApi = (typeof MeanRetentionCalculationApi)[keyof typeof MeanRetentionCalculationApi]

export const MeanRetentionCalculationApi = {
    Simple: 'simple',
    Weighted: 'weighted',
    None: 'none',
} as const

export type RetentionPeriodApi = (typeof RetentionPeriodApi)[keyof typeof RetentionPeriodApi]

export const RetentionPeriodApi = {
    Hour: 'Hour',
    Day: 'Day',
    Week: 'Week',
    Month: 'Month',
} as const

export type RetentionReferenceApi = (typeof RetentionReferenceApi)[keyof typeof RetentionReferenceApi]

export const RetentionReferenceApi = {
    Total: 'total',
    Previous: 'previous',
} as const

export type RetentionTypeApi = (typeof RetentionTypeApi)[keyof typeof RetentionTypeApi]

export const RetentionTypeApi = {
    RetentionRecurring: 'retention_recurring',
    RetentionFirstTime: 'retention_first_time',
    RetentionFirstEverOccurrence: 'retention_first_ever_occurrence',
} as const

export type RetentionEntityKindApi = (typeof RetentionEntityKindApi)[keyof typeof RetentionEntityKindApi]

export const RetentionEntityKindApi = {
    ActionsNode: 'ActionsNode',
    EventsNode: 'EventsNode',
} as const

export type EntityTypeApi = (typeof EntityTypeApi)[keyof typeof EntityTypeApi]

export const EntityTypeApi = {
    Actions: 'actions',
    Events: 'events',
    DataWarehouse: 'data_warehouse',
    NewEntity: 'new_entity',
    Groups: 'groups',
} as const

export type TimeWindowModeApi = (typeof TimeWindowModeApi)[keyof typeof TimeWindowModeApi]

export const TimeWindowModeApi = {
    StrictCalendarDates: 'strict_calendar_dates',
    '24HourWindows': '24_hour_windows',
} as const

export type FunnelPathTypeApi = (typeof FunnelPathTypeApi)[keyof typeof FunnelPathTypeApi]

export const FunnelPathTypeApi = {
    FunnelPathBeforeStep: 'funnel_path_before_step',
    FunnelPathBetweenSteps: 'funnel_path_between_steps',
    FunnelPathAfterStep: 'funnel_path_after_step',
} as const

export type PathTypeApi = (typeof PathTypeApi)[keyof typeof PathTypeApi]

export const PathTypeApi = {
    Pageview: '$pageview',
    Screen: '$screen',
    CustomEvent: 'custom_event',
    Hogql: 'hogql',
} as const

export type StickinessQueryResponseApiResultsItem = { [key: string]: unknown }

export type StickinessComputationModeApi =
    (typeof StickinessComputationModeApi)[keyof typeof StickinessComputationModeApi]

export const StickinessComputationModeApi = {
    NonCumulative: 'non_cumulative',
    Cumulative: 'cumulative',
} as const

export type StickinessOperatorApi = (typeof StickinessOperatorApi)[keyof typeof StickinessOperatorApi]

export const StickinessOperatorApi = {
    Gte: 'gte',
    Lte: 'lte',
    Exact: 'exact',
} as const

/**
 * Customizations for the appearance of result datasets.
 */
export type StickinessFilterApiResultCustomizations =
    | { [key: string]: ResultCustomizationByValueApi }
    | { [key: string]: ResultCustomizationByPositionApi }
    | null

export type LifecycleToggleApi = (typeof LifecycleToggleApi)[keyof typeof LifecycleToggleApi]

export const LifecycleToggleApi = {
    New: 'new',
    Resurrecting: 'resurrecting',
    Returning: 'returning',
    Dormant: 'dormant',
} as const

export type LifecycleQueryResponseApiResultsItem = { [key: string]: unknown }

export type LifecycleDataWarehouseNodeApiResponse = { [key: string]: unknown } | null

export type WebStatsBreakdownApi = (typeof WebStatsBreakdownApi)[keyof typeof WebStatsBreakdownApi]

export const WebStatsBreakdownApi = {
    Page: 'Page',
    InitialPage: 'InitialPage',
    ExitPage: 'ExitPage',
    ExitClick: 'ExitClick',
    PreviousPage: 'PreviousPage',
    ScreenName: 'ScreenName',
    InitialChannelType: 'InitialChannelType',
    InitialReferringDomain: 'InitialReferringDomain',
    InitialReferringURL: 'InitialReferringURL',
    InitialUTMSource: 'InitialUTMSource',
    InitialUTMCampaign: 'InitialUTMCampaign',
    InitialUTMMedium: 'InitialUTMMedium',
    InitialUTMTerm: 'InitialUTMTerm',
    InitialUTMContent: 'InitialUTMContent',
    InitialUTMSourceMediumCampaign: 'InitialUTMSourceMediumCampaign',
    Browser: 'Browser',
    Os: 'OS',
    Viewport: 'Viewport',
    DeviceType: 'DeviceType',
    Country: 'Country',
    Region: 'Region',
    City: 'City',
    Timezone: 'Timezone',
    Language: 'Language',
    FrustrationMetrics: 'FrustrationMetrics',
} as const

export type WebAnalyticsOrderByFieldsApi =
    (typeof WebAnalyticsOrderByFieldsApi)[keyof typeof WebAnalyticsOrderByFieldsApi]

export const WebAnalyticsOrderByFieldsApi = {
    Visitors: 'Visitors',
    Views: 'Views',
    AvgTimeOnPage: 'AvgTimeOnPage',
    Clicks: 'Clicks',
    BounceRate: 'BounceRate',
    AverageScrollPercentage: 'AverageScrollPercentage',
    ScrollGt80Percentage: 'ScrollGt80Percentage',
    TotalConversions: 'TotalConversions',
    UniqueConversions: 'UniqueConversions',
    ConversionRate: 'ConversionRate',
    ConvertingUsers: 'ConvertingUsers',
    RageClicks: 'RageClicks',
    DeadClicks: 'DeadClicks',
    Errors: 'Errors',
} as const

export type WebAnalyticsOrderByDirectionApi =
    (typeof WebAnalyticsOrderByDirectionApi)[keyof typeof WebAnalyticsOrderByDirectionApi]

export const WebAnalyticsOrderByDirectionApi = {
    Asc: 'ASC',
    Desc: 'DESC',
} as const

export type WebAnalyticsItemKindApi = (typeof WebAnalyticsItemKindApi)[keyof typeof WebAnalyticsItemKindApi]

export const WebAnalyticsItemKindApi = {
    Unit: 'unit',
    DurationS: 'duration_s',
    Percentage: 'percentage',
    Currency: 'currency',
} as const

export interface ActionsPieApi {
    disableHoverOffset?: boolean | null
    hideAggregation?: boolean | null
}

export interface RetentionApi {
    hideLineGraph?: boolean | null
    hideSizeColumn?: boolean | null
    useSmallLayout?: boolean | null
}

export type DataTableNodeViewPropsContextTypeApi =
    (typeof DataTableNodeViewPropsContextTypeApi)[keyof typeof DataTableNodeViewPropsContextTypeApi]

export const DataTableNodeViewPropsContextTypeApi = {
    EventDefinition: 'event_definition',
    TeamColumns: 'team_columns',
} as const

export type DataTableNodeApiKind = (typeof DataTableNodeApiKind)[keyof typeof DataTableNodeApiKind]

export const DataTableNodeApiKind = {
    DataTableNode: 'DataTableNode',
} as const

export interface ResponseApi {
    columns: unknown[]
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Cursor for fetching the next page of results */
    nextCursor?: string | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types: string[]
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response1Api {
    columns: unknown[]
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    limit: number
    missing_actors_count?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset: number
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: string[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response2Api {
    columns: unknown[]
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    kind?: 'GroupsQuery'
    limit: number
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset: number
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types: string[]
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export type QueryIndexUsageApi = (typeof QueryIndexUsageApi)[keyof typeof QueryIndexUsageApi]

export const QueryIndexUsageApi = {
    Undecisive: 'undecisive',
    No: 'no',
    Partial: 'partial',
    Yes: 'yes',
} as const

export interface Response3Api {
    /** Executed ClickHouse query */
    clickhouse?: string | null
    /** Returned columns */
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Query explanation output */
    explain?: string[] | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Query metadata output */
    metadata?: HogQLMetadataResponseApi | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Input query string */
    query?: string | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Types of returned columns */
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response4Api {
    dateFrom?: string | null
    dateTo?: string | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: WebOverviewItemApi[]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    usedLazyPrecompute?: boolean | null
    usedPreAggregatedTables?: boolean | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response5Api {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    usedLazyPrecompute?: boolean | null
    usedPreAggregatedTables?: boolean | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response6Api {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response7Api {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Whether the response was served from the lazy precompute path. */
    usedLazyPrecompute?: boolean | null
    /** Whether the response was served from a precomputed table. */
    usedPreAggregatedTables?: boolean | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response8Api {
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    /**
     * @minItems 1
     * @maxItems 1
     */
    results: WebVitalsPathBreakdownResultApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    usedLazyPrecompute?: boolean | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response9Api {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response10Api {
    columns: unknown[]
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types: string[]
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response11Api {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response12Api {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response13Api {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: RevenueAnalyticsMRRQueryResultItemApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export type RevenueAnalyticsOverviewItemKeyApi =
    (typeof RevenueAnalyticsOverviewItemKeyApi)[keyof typeof RevenueAnalyticsOverviewItemKeyApi]

export const RevenueAnalyticsOverviewItemKeyApi = {
    Revenue: 'revenue',
    PayingCustomerCount: 'paying_customer_count',
    AvgRevenuePerCustomer: 'avg_revenue_per_customer',
} as const

export interface Response14Api {
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: RevenueAnalyticsOverviewItemApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response15Api {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response16Api {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response18Api {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: MarketingAnalyticsItemApi[][]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export type Response19ApiResults = { [key: string]: MarketingAnalyticsItemApi }

export interface Response19Api {
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    /** Generated HogQL query. */
    hogql?: string | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: Response19ApiResults
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response20Api {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: MarketingAnalyticsItemApi[][]
    samplingRate?: SamplingRateApi | null
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface VolumeBucketApi {
    label: string
    value: number
}

export type ErrorTrackingIssueAssigneeTypeApi =
    (typeof ErrorTrackingIssueAssigneeTypeApi)[keyof typeof ErrorTrackingIssueAssigneeTypeApi]

export const ErrorTrackingIssueAssigneeTypeApi = {
    User: 'user',
    Role: 'role',
} as const

export type IntegrationKindApi = (typeof IntegrationKindApi)[keyof typeof IntegrationKindApi]

export const IntegrationKindApi = {
    Slack: 'slack',
    Salesforce: 'salesforce',
    Hubspot: 'hubspot',
    GooglePubsub: 'google-pubsub',
    GoogleCloudServiceAccount: 'google-cloud-service-account',
    GoogleCloudStorage: 'google-cloud-storage',
    GoogleAds: 'google-ads',
    GoogleSearchConsole: 'google-search-console',
    GoogleSheets: 'google-sheets',
    LinkedinAds: 'linkedin-ads',
    Snapchat: 'snapchat',
    Stripe: 'stripe',
    Intercom: 'intercom',
    Email: 'email',
    Twilio: 'twilio',
    Linear: 'linear',
    Github: 'github',
    Gitlab: 'gitlab',
    MetaAds: 'meta-ads',
    Clickup: 'clickup',
    RedditAds: 'reddit-ads',
    Databricks: 'databricks',
    TiktokAds: 'tiktok-ads',
    BingAds: 'bing-ads',
    Vercel: 'vercel',
    AzureBlob: 'azure-blob',
    Firebase: 'firebase',
    Jira: 'jira',
    PinterestAds: 'pinterest-ads',
    CustomerioApp: 'customerio-app',
    CustomerioWebhook: 'customerio-webhook',
    CustomerioTrack: 'customerio-track',
} as const

export interface FirstEventApi {
    distinct_id: string
    properties: string
    timestamp: string
    uuid: string
}

export interface LastEventApi {
    distinct_id: string
    properties: string
    timestamp: string
    uuid: string
}

export type ErrorTrackingIssueStatusApi = (typeof ErrorTrackingIssueStatusApi)[keyof typeof ErrorTrackingIssueStatusApi]

export const ErrorTrackingIssueStatusApi = {
    Archived: 'archived',
    Active: 'active',
    Resolved: 'resolved',
    PendingRelease: 'pending_release',
    Suppressed: 'suppressed',
} as const

export interface Response21Api {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: ErrorTrackingIssueApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface PopulationApi {
    both: number
    exception_only: number
    neither: number
    success_only: number
}

export interface Response22Api {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: ErrorTrackingCorrelatedIssueApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export type ExperimentSignificanceCodeApi =
    (typeof ExperimentSignificanceCodeApi)[keyof typeof ExperimentSignificanceCodeApi]

export const ExperimentSignificanceCodeApi = {
    Significant: 'significant',
    NotEnoughExposure: 'not_enough_exposure',
    LowWinProbability: 'low_win_probability',
    HighLoss: 'high_loss',
    HighPValue: 'high_p_value',
} as const

export type Response23ApiCredibleIntervals = { [key: string]: number[] }

export type Response23ApiInsightItemItem = { [key: string]: unknown }

export type Response23ApiProbability = { [key: string]: number }

export interface Response23Api {
    credible_intervals: Response23ApiCredibleIntervals
    expected_loss: number
    funnels_query?: FunnelsQueryApi | null
    insight: Response23ApiInsightItemItem[][]
    kind?: 'ExperimentFunnelsQuery'
    probability: Response23ApiProbability
    significance_code: ExperimentSignificanceCodeApi
    significant: boolean
    stats_version?: number | null
    variants: ExperimentVariantFunnelsBaseStatsApi[]
    /** Data warehouse sync warnings — see AnalyticsQueryResponseBase.warnings for semantics. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export type Response24ApiCredibleIntervals = { [key: string]: number[] }

export type Response24ApiInsightItem = { [key: string]: unknown }

export type Response24ApiProbability = { [key: string]: number }

export interface Response24Api {
    count_query?: TrendsQueryApi | null
    credible_intervals: Response24ApiCredibleIntervals
    exposure_query?: TrendsQueryApi | null
    insight: Response24ApiInsightItem[]
    kind?: 'ExperimentTrendsQuery'
    p_value: number
    probability: Response24ApiProbability
    significance_code: ExperimentSignificanceCodeApi
    significant: boolean
    stats_version?: number | null
    variants: ExperimentVariantTrendsBaseStatsApi[]
    /** Data warehouse sync warnings — see AnalyticsQueryResponseBase.warnings for semantics. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export type AIEventTypeApi = (typeof AIEventTypeApi)[keyof typeof AIEventTypeApi]

export const AIEventTypeApi = {
    AiGeneration: '$ai_generation',
    AiEmbedding: '$ai_embedding',
    AiSpan: '$ai_span',
    AiTrace: '$ai_trace',
    AiMetric: '$ai_metric',
    AiFeedback: '$ai_feedback',
    AiEvaluation: '$ai_evaluation',
    AiTag: '$ai_tag',
    AiTraceSummary: '$ai_trace_summary',
    AiGenerationSummary: '$ai_generation_summary',
    AiTraceClusters: '$ai_trace_clusters',
    AiGenerationClusters: '$ai_generation_clusters',
} as const

export type LLMTraceEventApiProperties = { [key: string]: unknown }

export type LLMTracePersonApiProperties = { [key: string]: unknown }

export interface Response25Api {
    columns?: string[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: LLMTraceApi[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response26Api {
    columns?: unknown[] | null
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql?: string | null
    limit?: number | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset?: number | null
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types?: unknown[] | null
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export interface Response27Api {
    columns: unknown[]
    /** Query error. Returned only if 'explain' or `modifiers.debug` is true. Throws an error otherwise. */
    error?: string | null
    hasMore?: boolean | null
    /** Generated HogQL query. */
    hogql: string
    kind?: 'AccountsQuery'
    limit: number
    /** When `metrics` is set on the query, the aggregated values in the same order. */
    metricsResults?: (number | null)[] | null
    /** Modifiers used when performing the query */
    modifiers?: HogQLQueryModifiersApi | null
    offset: number
    /** Query status indicates whether next to the provided data, a query is still running. */
    query_status?: QueryStatusApi | null
    /** The resolved previous/comparison period date range, when comparing against another period */
    resolved_compare_date_range?: ResolvedDateRangeResponseApi | null
    /** The date range used for the query */
    resolved_date_range?: ResolvedDateRangeResponseApi | null
    results: unknown[][]
    /** Measured timings for different parts of the query generation process */
    timings?: QueryTimingApi[] | null
    types: string[]
    /** Warnings about data warehouse sources referenced by the query whose latest sync failed, is paused, hit a billing limit, or is otherwise stale. Results may not reflect current source data. Accumulated across every HogQL execution that contributes to this response — so insights backed by warehouse tables (Trends, Funnels, etc.) receive the same warnings as raw HogQL queries. */
    warnings?: DataWarehouseSyncWarningApi[] | null
}

export type TaxonomicFilterGroupTypeApi = (typeof TaxonomicFilterGroupTypeApi)[keyof typeof TaxonomicFilterGroupTypeApi]

export const TaxonomicFilterGroupTypeApi = {
    Metadata: 'metadata',
    Actions: 'actions',
    Cohorts: 'cohorts',
    CohortsWithAll: 'cohorts_with_all',
    DataWarehouse: 'data_warehouse',
    DataWarehouseProperties: 'data_warehouse_properties',
    DataWarehousePersonProperties: 'data_warehouse_person_properties',
    Elements: 'elements',
    Events: 'events',
    InternalEvents: 'internal_events',
    InternalEventProperties: 'internal_event_properties',
    EventProperties: 'event_properties',
    EventFeatureFlags: 'event_feature_flags',
    EventMetadata: 'event_metadata',
    NumericalEventProperties: 'numerical_event_properties',
    PersonProperties: 'person_properties',
    PageviewUrls: 'pageview_urls',
    PageviewEvents: 'pageview_events',
    Screens: 'screens',
    ScreenEvents: 'screen_events',
    EmailAddresses: 'email_addresses',
    AutocaptureEvents: 'autocapture_events',
    CustomEvents: 'custom_events',
    Wildcard: 'wildcard',
    Groups: 'groups',
    Persons: 'persons',
    FeatureFlags: 'feature_flags',
    Insights: 'insights',
    Experiments: 'experiments',
    Plugins: 'plugins',
    Dashboards: 'dashboards',
    NameGroups: 'name_groups',
    SessionProperties: 'session_properties',
    HogqlExpression: 'hogql_expression',
    Notebooks: 'notebooks',
    LogEntries: 'log_entries',
    ErrorTrackingIssues: 'error_tracking_issues',
    Logs: 'logs',
    LogAttributes: 'log_attributes',
    LogResourceAttributes: 'log_resource_attributes',
    Spans: 'spans',
    SpanAttributes: 'span_attributes',
    SpanResourceAttributes: 'span_resource_attributes',
    Replay: 'replay',
    ReplaySavedFilters: 'replay_saved_filters',
    RevenueAnalyticsProperties: 'revenue_analytics_properties',
    Resources: 'resources',
    ErrorTrackingProperties: 'error_tracking_properties',
    ActivityLogProperties: 'activity_log_properties',
    MaxAiContext: 'max_ai_context',
    WorkflowVariables: 'workflow_variables',
    SuggestedFilters: 'suggested_filters',
    RecentFilters: 'recent_filters',
    PinnedFilters: 'pinned_filters',
    Empty: 'empty',
} as const

export type HrefMatchingApi = (typeof HrefMatchingApi)[keyof typeof HrefMatchingApi]

export const HrefMatchingApi = {
    Contains: 'contains',
    Exact: 'exact',
    Regex: 'regex',
} as const

export type TextMatchingApi = (typeof TextMatchingApi)[keyof typeof TextMatchingApi]

export const TextMatchingApi = {
    Contains: 'contains',
    Exact: 'exact',
    Regex: 'regex',
} as const

export type UrlMatchingApi = (typeof UrlMatchingApi)[keyof typeof UrlMatchingApi]

export const UrlMatchingApi = {
    Contains: 'contains',
    Exact: 'exact',
    Regex: 'regex',
} as const

export type CompareApi = (typeof CompareApi)[keyof typeof CompareApi]

export const CompareApi = {
    Current: 'current',
    Previous: 'previous',
} as const

export type PersonsNodeApiResponse = { [key: string]: unknown } | null

export type FunnelCorrelationResultsTypeApi =
    (typeof FunnelCorrelationResultsTypeApi)[keyof typeof FunnelCorrelationResultsTypeApi]

export const FunnelCorrelationResultsTypeApi = {
    Events: 'events',
    Properties: 'properties',
    EventWithProperties: 'event_with_properties',
} as const

export type CorrelationTypeApi = (typeof CorrelationTypeApi)[keyof typeof CorrelationTypeApi]

export const CorrelationTypeApi = {
    Success: 'success',
    Failure: 'failure',
} as const

export type EventDefinitionApiProperties = { [key: string]: unknown }

export type ExperimentEventExposureConfigApiResponse = { [key: string]: unknown } | null

export type MultipleVariantHandlingApi = (typeof MultipleVariantHandlingApi)[keyof typeof MultipleVariantHandlingApi]

export const MultipleVariantHandlingApi = {
    Exclude: 'exclude',
    FirstSeen: 'first_seen',
} as const

export type ExperimentMetricGoalApi = (typeof ExperimentMetricGoalApi)[keyof typeof ExperimentMetricGoalApi]

export const ExperimentMetricGoalApi = {
    Increase: 'increase',
    Decrease: 'decrease',
} as const

export type ExperimentDataWarehouseNodeApiResponse = { [key: string]: unknown } | null

export type ExperimentMeanMetricApiResponse = { [key: string]: unknown } | null

export type ExperimentFunnelMetricApiResponse = { [key: string]: unknown } | null

export type ExperimentRatioMetricApiResponse = { [key: string]: unknown } | null

export type StartHandlingApi = (typeof StartHandlingApi)[keyof typeof StartHandlingApi]

export const StartHandlingApi = {
    FirstSeen: 'first_seen',
    LastSeen: 'last_seen',
} as const

export type ExperimentRetentionMetricApiResponse = { [key: string]: unknown } | null

export type PrecomputationModeApi = (typeof PrecomputationModeApi)[keyof typeof PrecomputationModeApi]

export const PrecomputationModeApi = {
    Precomputed: 'precomputed',
    Direct: 'direct',
} as const

export type ExperimentStatsValidationFailureApi =
    (typeof ExperimentStatsValidationFailureApi)[keyof typeof ExperimentStatsValidationFailureApi]

export const ExperimentStatsValidationFailureApi = {
    NotEnoughExposures: 'not-enough-exposures',
    BaselineMeanIsZero: 'baseline-mean-is-zero',
    NotEnoughMetricData: 'not-enough-metric-data',
} as const

export type ExperimentQueryResponseApiCredibleIntervals = { [key: string]: number[] } | null

export type ExperimentQueryResponseApiInsight = { [key: string]: unknown }[] | null

export type ExperimentQueryResponseApiProbability = { [key: string]: number } | null

/**
 * Constant values that can be referenced with the {placeholder} syntax in the query
 */
export type HogQLQueryApiValues = { [key: string]: unknown } | null

/**
 * Variables to be substituted into the query
 */
export type HogQLQueryApiVariables = { [key: string]: HogQLVariableApi } | null

export type WebVitalsMetricApi = (typeof WebVitalsMetricApi)[keyof typeof WebVitalsMetricApi]

export const WebVitalsMetricApi = {
    Inp: 'INP',
    Lcp: 'LCP',
    Cls: 'CLS',
    Fcp: 'FCP',
} as const

export type WebVitalsPercentileApi = (typeof WebVitalsPercentileApi)[keyof typeof WebVitalsPercentileApi]

export const WebVitalsPercentileApi = {
    P75: 'p75',
    P90: 'p90',
    P99: 'p99',
} as const

export interface FiltersApi {
    dateRange?: DateRangeApi | null
    properties?: SessionPropertyFilterApi[] | null
}

export type SessionAttributionGroupByApi =
    (typeof SessionAttributionGroupByApi)[keyof typeof SessionAttributionGroupByApi]

export const SessionAttributionGroupByApi = {
    ChannelType: 'ChannelType',
    Medium: 'Medium',
    Source: 'Source',
    Campaign: 'Campaign',
    AdIds: 'AdIds',
    ReferringDomain: 'ReferringDomain',
    InitialURL: 'InitialURL',
} as const

export type SimpleIntervalTypeApi = (typeof SimpleIntervalTypeApi)[keyof typeof SimpleIntervalTypeApi]

export const SimpleIntervalTypeApi = {
    Day: 'day',
    Month: 'month',
} as const

export type RevenueAnalyticsTopCustomersGroupByApi =
    (typeof RevenueAnalyticsTopCustomersGroupByApi)[keyof typeof RevenueAnalyticsTopCustomersGroupByApi]

export const RevenueAnalyticsTopCustomersGroupByApi = {
    Month: 'month',
    All: 'all',
} as const

export type ConversionGoalFilter1ApiResponse = { [key: string]: unknown } | null

export type ConversionGoalFilter1ApiSchemaMap = { [key: string]: string | unknown }

export interface ConversionGoalFilter1Api {
    conversion_goal_id: string
    conversion_goal_name: string
    custom_name?: string | null
    /** The event or `null` for all events. */
    event?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    kind?: 'EventsNode'
    limit?: number | null
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'unique_group'
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Columns to order by */
    orderBy?: string[] | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    response?: ConversionGoalFilter1ApiResponse
    schema_map: ConversionGoalFilter1ApiSchemaMap
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type ConversionGoalFilter2ApiResponse = { [key: string]: unknown } | null

export type ConversionGoalFilter2ApiSchemaMap = { [key: string]: string | unknown }

export interface ConversionGoalFilter2Api {
    conversion_goal_id: string
    conversion_goal_name: string
    custom_name?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    id: number
    kind?: 'ActionsNode'
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'unique_group'
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    response?: ConversionGoalFilter2ApiResponse
    schema_map: ConversionGoalFilter2ApiSchemaMap
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type ConversionGoalFilter3ApiResponse = { [key: string]: unknown } | null

export type ConversionGoalFilter3ApiSchemaMap = { [key: string]: string | unknown }

export interface ConversionGoalFilter3Api {
    conversion_goal_id: string
    conversion_goal_name: string
    custom_name?: string | null
    distinct_id_field: string
    dw_source_type?: string | null
    /** Fixed properties in the query, can't be edited in the interface (e.g. scoping down by person) */
    fixedProperties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    id: string
    id_field: string
    kind?: 'DataWarehouseNode'
    math?:
        | BaseMathTypeApi
        | FunnelMathTypeApi
        | PropertyMathTypeApi
        | CountPerActorMathTypeApi
        | ExperimentMetricMathTypeApi
        | CalendarHeatmapMathTypeApi
        | 'unique_group'
        | 'hogql'
        | null
    math_group_type_index?: MathGroupTypeIndexApi | null
    math_hogql?: string | null
    math_multiplier?: number | null
    math_property?: string | null
    math_property_revenue_currency?: RevenueCurrencyPropertyConfigApi | null
    math_property_type?: string | null
    name?: string | null
    optionalInFunnel?: boolean | null
    /** Properties configurable in the interface */
    properties?:
        | (
              | EventPropertyFilterApi
              | PersonPropertyFilterApi
              | ElementPropertyFilterApi
              | EventMetadataPropertyFilterApi
              | SessionPropertyFilterApi
              | CohortPropertyFilterApi
              | RecordingPropertyFilterApi
              | LogEntryPropertyFilterApi
              | GroupPropertyFilterApi
              | FeaturePropertyFilterApi
              | FlagPropertyFilterApi
              | HogQLPropertyFilterApi
              | EmptyPropertyFilterApi
              | DataWarehousePropertyFilterApi
              | DataWarehousePersonPropertyFilterApi
              | ErrorTrackingIssueFilterApi
              | LogPropertyFilterApi
              | SpanPropertyFilterApi
              | RevenueAnalyticsPropertyFilterApi
              | WorkflowVariablePropertyFilterApi
          )[]
        | null
    response?: ConversionGoalFilter3ApiResponse
    schema_map: ConversionGoalFilter3ApiSchemaMap
    table_name: string
    timestamp_field: string
    /** version of the node, used for schema migrations */
    version?: number | null
}

export type MarketingAnalyticsDrillDownLevelApi =
    (typeof MarketingAnalyticsDrillDownLevelApi)[keyof typeof MarketingAnalyticsDrillDownLevelApi]

export const MarketingAnalyticsDrillDownLevelApi = {
    Channel: 'channel',
    Source: 'source',
    Campaign: 'campaign',
    AdGroup: 'ad_group',
    Ad: 'ad',
    Medium: 'medium',
    Content: 'content',
    Term: 'term',
} as const

export type MarketingAnalyticsOrderByEnumApi =
    (typeof MarketingAnalyticsOrderByEnumApi)[keyof typeof MarketingAnalyticsOrderByEnumApi]

export const MarketingAnalyticsOrderByEnumApi = {
    Asc: 'ASC',
    Desc: 'DESC',
} as const

export type MarketingAnalyticsAggregatedQueryResponseApiResults = { [key: string]: MarketingAnalyticsItemApi }

export type ErrorTrackingOrderByApi = (typeof ErrorTrackingOrderByApi)[keyof typeof ErrorTrackingOrderByApi]

export const ErrorTrackingOrderByApi = {
    LastSeen: 'last_seen',
    FirstSeen: 'first_seen',
    Occurrences: 'occurrences',
    Users: 'users',
    Sessions: 'sessions',
} as const

export type OrderDirection2Api = (typeof OrderDirection2Api)[keyof typeof OrderDirection2Api]

export const OrderDirection2Api = {
    Asc: 'ASC',
    Desc: 'DESC',
} as const

export type ExperimentFunnelsQueryResponseApiCredibleIntervals = { [key: string]: number[] }

export type ExperimentFunnelsQueryResponseApiInsightItemItem = { [key: string]: unknown }

export type ExperimentFunnelsQueryResponseApiProbability = { [key: string]: number }

export type ExperimentTrendsQueryResponseApiCredibleIntervals = { [key: string]: number[] }

export type ExperimentTrendsQueryResponseApiInsightItem = { [key: string]: unknown }

export type ExperimentTrendsQueryResponseApiProbability = { [key: string]: number }

export type EndpointsUsageBreakdownApi = (typeof EndpointsUsageBreakdownApi)[keyof typeof EndpointsUsageBreakdownApi]

export const EndpointsUsageBreakdownApi = {
    Endpoint: 'Endpoint',
    MaterializationType: 'MaterializationType',
    ApiKey: 'ApiKey',
    Status: 'Status',
} as const

export type MaterializationTypeApi = (typeof MaterializationTypeApi)[keyof typeof MaterializationTypeApi]

export const MaterializationTypeApi = {
    Materialized: 'materialized',
    Inline: 'inline',
} as const

export type EndpointsUsageOrderByFieldApi =
    (typeof EndpointsUsageOrderByFieldApi)[keyof typeof EndpointsUsageOrderByFieldApi]

export const EndpointsUsageOrderByFieldApi = {
    Requests: 'requests',
    BytesRead: 'bytes_read',
    CpuSeconds: 'cpu_seconds',
    AvgQueryDurationMs: 'avg_query_duration_ms',
    ErrorRate: 'error_rate',
} as const

export type EndpointsUsageOrderByDirectionApi =
    (typeof EndpointsUsageOrderByDirectionApi)[keyof typeof EndpointsUsageOrderByDirectionApi]

export const EndpointsUsageOrderByDirectionApi = {
    Asc: 'ASC',
    Desc: 'DESC',
} as const

export type DataTableNodeApiResponse =
    | { [key: string]: unknown }
    | ResponseApi
    | Response1Api
    | Response2Api
    | Response3Api
    | Response4Api
    | Response5Api
    | Response6Api
    | Response7Api
    | Response8Api
    | Response9Api
    | Response10Api
    | Response11Api
    | Response12Api
    | Response13Api
    | Response14Api
    | Response15Api
    | Response16Api
    | Response18Api
    | Response19Api
    | Response20Api
    | Response21Api
    | Response22Api
    | Response23Api
    | Response24Api
    | Response25Api
    | Response26Api
    | Response27Api
    | null

export type GradientScaleModeApi = (typeof GradientScaleModeApi)[keyof typeof GradientScaleModeApi]

export const GradientScaleModeApi = {
    Absolute: 'absolute',
    Relative: 'relative',
} as const

export type HeatmapSortOrderApi = (typeof HeatmapSortOrderApi)[keyof typeof HeatmapSortOrderApi]

export const HeatmapSortOrderApi = {
    Asc: 'asc',
    Desc: 'desc',
} as const

export type ScaleApi = (typeof ScaleApi)[keyof typeof ScaleApi]

export const ScaleApi = {
    Linear: 'linear',
    Logarithmic: 'logarithmic',
} as const

export type DisplayTypeApi = (typeof DisplayTypeApi)[keyof typeof DisplayTypeApi]

export const DisplayTypeApi = {
    Auto: 'auto',
    Line: 'line',
    Bar: 'bar',
    Area: 'area',
} as const

export type YAxisPositionApi = (typeof YAxisPositionApi)[keyof typeof YAxisPositionApi]

export const YAxisPositionApi = {
    Left: 'left',
    Right: 'right',
} as const

export type StyleApi = (typeof StyleApi)[keyof typeof StyleApi]

export const StyleApi = {
    None: 'none',
    Number: 'number',
    Short: 'short',
    Percent: 'percent',
} as const

export interface SettingsApi {
    display?: ChartSettingsDisplayApi | null
    formatting?: ChartSettingsFormattingApi | null
}

/**
 * Per-breakdown-value color customizations. Keyed by the raw breakdown column value.
 */
export type ChartSettingsApiResultCustomizations = { [key: string]: ResultCustomizationByValueApi } | null

export type DataVisualizationNodeApiKind =
    (typeof DataVisualizationNodeApiKind)[keyof typeof DataVisualizationNodeApiKind]

export const DataVisualizationNodeApiKind = {
    DataVisualizationNode: 'DataVisualizationNode',
} as const

export type ColorModeApi = (typeof ColorModeApi)[keyof typeof ColorModeApi]

export const ColorModeApi = {
    Light: 'light',
    Dark: 'dark',
} as const

export type HogQueryApiKind = (typeof HogQueryApiKind)[keyof typeof HogQueryApiKind]

export const HogQueryApiKind = {
    HogQuery: 'HogQuery',
} as const

/**
 * The query definition for this insight. The `kind` field determines the query type:
 * - `InsightVizNode` — product analytics (trends, funnels, retention, paths, stickiness, lifecycle)
 * - `DataVisualizationNode` — SQL insights using HogQL
 * - `DataTableNode` — raw data tables
 * - `HogQuery` — Hog language queries
 */
export type _InsightQuerySchemaApi = InsightVizNodeApi | DataTableNodeApi | DataVisualizationNodeApi | HogQueryApi

export interface DashboardTileBasicApi {
    readonly id: number
    readonly dashboard_id: number
    /** @nullable */
    deleted?: boolean | null
}

/**
 * @nullable
 */
export type InsightApiResolvedDateRange = {
    readonly date_from?: string
    readonly date_to?: string
} | null

/**
 * Simplified serializer to speed response times when loading large amounts of objects.
 */
export interface InsightApi {
    readonly id: number
    readonly short_id: string
    /**
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    derived_name?: string | null
    query?: _InsightQuerySchemaApi | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    order?: number | null
    deleted?: boolean
    /**
     *         DEPRECATED. Will be removed in a future release. Use dashboard_tiles instead.
     *         A dashboard ID for each of the dashboards that this insight is displayed on.
     *          */
    dashboards?: number[]
    /**
     *     A dashboard tile ID and dashboard_id for each of the dashboards that this insight is displayed on.
     *      */
    readonly dashboard_tiles: readonly DashboardTileBasicApi[]
    /**
     *
     *     The datetime this insight's results were generated.
     *     If added to one or more dashboards the insight can be refreshed separately on each.
     *     Returns the appropriate last_refresh datetime for the context the insight is viewed in
     *     (see from_dashboard query parameter).
     *
     * @nullable
     */
    readonly last_refresh: string | null
    /**
     * The target age of the cached results for this insight.
     * @nullable
     */
    readonly cache_target_age: string | null
    /**
     *
     *     The earliest possible datetime at which we'll allow the cached results for this insight to be refreshed
     *     by querying the database.
     *
     * @nullable
     */
    readonly next_allowed_client_refresh: string | null
    readonly result: unknown
    /** @nullable */
    readonly hasMore: boolean | null
    /** @nullable */
    readonly columns: readonly string[] | null
    /** @nullable */
    readonly created_at: string | null
    readonly created_by: UserBasicApi
    /**
     * @maxLength 400
     * @nullable
     */
    description?: string | null
    readonly updated_at: string
    tags?: unknown[]
    favorited?: boolean
    readonly last_modified_at: string
    readonly last_modified_by: UserBasicApi
    readonly is_sample: boolean
    readonly effective_restriction_level: EffectivePrivilegeLevelEnumApi
    readonly effective_privilege_level: EffectivePrivilegeLevelEnumApi
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    /**
     * The timezone this chart is displayed in.
     * @nullable
     */
    readonly timezone: string | null
    readonly is_cached: boolean
    readonly query_status: unknown
    /** @nullable */
    readonly hogql: string | null
    /** @nullable */
    readonly types: readonly unknown[] | null
    /** @nullable */
    readonly resolved_date_range: InsightApiResolvedDateRange
    _create_in_folder?: string
    readonly alerts: readonly unknown[]
    /** @nullable */
    readonly last_viewed_at: string | null
    /** How this row matched the `search` query parameter: `exact` (the term is a case-insensitive substring of a searched field) or `similar` (a fuzzy trigram match only). Results are ordered exact-first. Null when the list is not filtered by `search`. */
    readonly search_match_type: SearchMatchTypeEnumApi | null
}

export interface TextApi {
    readonly id: number
    readonly created_by: UserBasicApi
    readonly last_modified_by: UserBasicApi
    /**
     * @maxLength 4000
     * @nullable
     */
    body?: string | null
    readonly dashboard_tiles: readonly DashboardTileBasicApi[]
    readonly last_modified_at: string
    team: number
}

/**
 * * `left` - left
 * * `right` - right
 */
export type PlacementEnumApi = (typeof PlacementEnumApi)[keyof typeof PlacementEnumApi]

export const PlacementEnumApi = {
    Left: 'left',
    Right: 'right',
} as const

/**
 * * `primary` - Primary
 * * `secondary` - Secondary
 */
export type StyleEnumApi = (typeof StyleEnumApi)[keyof typeof StyleEnumApi]

export const StyleEnumApi = {
    Primary: 'primary',
    Secondary: 'secondary',
} as const

export interface ButtonTileApi {
    readonly id: string
    readonly created_by: UserBasicApi
    readonly last_modified_by: UserBasicApi
    /** @maxLength 2000 */
    url: string
    /** @maxLength 200 */
    text: string
    placement?: PlacementEnumApi
    readonly dashboard_tiles: readonly DashboardTileBasicApi[]
    style?: StyleEnumApi
    readonly last_modified_at: string
    team: number
}

export interface DashboardWidgetApi {
    readonly id: string
    readonly created_by: UserBasicApi
    readonly last_modified_by: UserBasicApi
    /**
     * Widget type identifier from the dashboard widget catalog.
     * @maxLength 64
     */
    widget_type: string
    /**
     * Optional custom display name for this widget tile. Falls back to the widget catalog label when unset.
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /** Optional markdown description shown on the dashboard tile when enabled. */
    description?: string
    /** Widget-specific configuration JSON for this widget type. */
    config?: DashboardWidgetConfigApi
    readonly dashboard_tiles: readonly DashboardTileBasicApi[]
    readonly last_modified_at: string
    team: number
}

export interface DashboardTileApi {
    id?: number
    insight: InsightApi
    text: TextApi
    button_tile: ButtonTileApi
    widget?: DashboardWidgetApi | null
    layouts?: unknown
    /**
     * @maxLength 400
     * @nullable
     */
    color?: string | null
    filters_overrides?: unknown
    /** @nullable */
    show_description?: boolean | null
    /** @nullable */
    transparent_background?: boolean | null
}

export interface DeleteTileRequestApi {
    /** ID of the dashboard tile to delete. Use dashboard-get to look up tile IDs. */
    tile_id: number
}

export interface MoveTileTileApi {
    /** Dashboard tile ID to move. */
    id: number
}

export interface MoveTileRequestApi {
    /** Destination dashboard ID. */
    to_dashboard: number
    /** Tile to move, identified by its dashboard tile ID. */
    tile: MoveTileTileApi
}

export interface PatchedMoveTileRequestApi {
    /** Destination dashboard ID. */
    to_dashboard?: number
    /** Tile to move, identified by its dashboard tile ID. */
    tile?: MoveTileTileApi
}

/**
 * * `preserve` - preserve
 * * `two_column` - two_column
 * * `full_width` - full_width
 */
export type LayoutEnumApi = (typeof LayoutEnumApi)[keyof typeof LayoutEnumApi]

export const LayoutEnumApi = {
    Preserve: 'preserve',
    TwoColumn: 'two_column',
    FullWidth: 'full_width',
} as const

export interface ReorderTilesRequestApi {
    /**
     * Array of tile IDs in the desired display order (top to bottom, left to right).
     * @minItems 1
     */
    tile_order: number[]
    /** How to size tiles when reordering. 'preserve' (default) keeps each tile's existing width and height and only repacks positions in the new order. 'two_column' forces a 6-wide × 5-tall grid (two tiles per row). 'full_width' forces each tile to span the full 12-column row at height 5.
     *
     * * `preserve` - preserve
     * * `two_column` - two_column
     * * `full_width` - full_width */
    layout?: LayoutEnumApi
}

/**
 * InsightSerializer restricted to identifiers + result only.
 */
export interface InsightResultApi {
    readonly id: number
    readonly short_id: string
    /** @nullable */
    readonly name: string | null
    /** @nullable */
    readonly derived_name: string | null
    readonly result: unknown
}

/**
 * DashboardTileSerializer restricted to tile id + insight result fields.
 */
export interface DashboardTileResultApi {
    id?: number
    insight: InsightResultApi
}

export interface RunInsightsResponseApi {
    /** Results for each insight tile on the dashboard. */
    results: DashboardTileResultApi[]
}

export interface DashboardWidgetRunResultApi {
    /** Dashboard tile ID for this widget result. */
    tile_id: number
    /**
     * Widget type identifier, or null when the tile was not found.
     * @nullable
     */
    widget_type: string | null
    /** Live widget query result payload. List widgets return results (array), limit (configured page size), hasMore (boolean), totalCount (matching rows for current filters), totalCountCapped (true when totalCount hit the widget max and more may exist), and optional offset/nextOffset. error_tracking_list results are issue summaries; session_replay_list results are recording metadata. */
    result: unknown
    /**
     * Error message when the widget could not be run.
     * @nullable
     */
    error: string | null
}

export interface RunWidgetsResponseApi {
    /** Per-tile widget run results. */
    results: DashboardWidgetRunResultApi[]
}

export interface UpdateTextTileRequestApi {
    /** ID of the dashboard tile to update. Use dashboard-get to look up tile IDs. */
    tile_id: number
    /**
     * New markdown body for the text tile. Omit to leave the body unchanged. Max 4000 characters.
     * @minLength 1
     * @maxLength 4000
     */
    body?: string
    /** New grid layout per breakpoint. Omit to leave the layout unchanged. */
    layouts?: TileLayoutsApi
    /**
     * New accent color name, empty string or null to clear. Omit to leave unchanged.
     * @maxLength 400
     * @nullable
     */
    color?: string | null
}

export interface _WidgetTileLayoutBoxOpenApiApi {
    /** Column position in the dashboard grid (0-indexed). */
    x?: number
    /** Row position in the dashboard grid (0-indexed). */
    y?: number
    /** Width in grid columns. The desktop grid is 12 columns wide. */
    w?: number
    /** Height in grid rows. */
    h?: number
}

export interface _WidgetTileLayoutsOpenApiApi {
    /** Layout for the standard (desktop) breakpoint. The grid is 12 columns wide. */
    sm?: _WidgetTileLayoutBoxOpenApiApi
    /** Layout for the small (mobile) breakpoint. The grid is 1 column wide. */
    xs?: _WidgetTileLayoutBoxOpenApiApi
}

export type ErrorTrackingListWidgetAddRequestOpenApiApiWidgetType =
    (typeof ErrorTrackingListWidgetAddRequestOpenApiApiWidgetType)[keyof typeof ErrorTrackingListWidgetAddRequestOpenApiApiWidgetType]

export const ErrorTrackingListWidgetAddRequestOpenApiApiWidgetType = {
    ErrorTrackingList: 'error_tracking_list',
} as const

export interface ErrorTrackingListWidgetAddRequestOpenApiApi {
    /**
     * Optional custom display name for the widget tile.
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /** Optional markdown description shown when show_description is enabled. */
    description?: string
    /** Optional react-grid-layout positions keyed by breakpoint (sm, xs). */
    layouts?: _WidgetTileLayoutsOpenApiApi
    /** Whether to show the description on the dashboard tile. */
    show_description?: boolean
    widget_type: ErrorTrackingListWidgetAddRequestOpenApiApiWidgetType
    /** Configuration for the top issues widget. */
    config: ErrorTrackingListWidgetConfigApi
}

export type SessionReplayListWidgetAddRequestOpenApiApiWidgetType =
    (typeof SessionReplayListWidgetAddRequestOpenApiApiWidgetType)[keyof typeof SessionReplayListWidgetAddRequestOpenApiApiWidgetType]

export const SessionReplayListWidgetAddRequestOpenApiApiWidgetType = {
    SessionReplayList: 'session_replay_list',
} as const

export interface SessionReplayListWidgetAddRequestOpenApiApi {
    /**
     * Optional custom display name for the widget tile.
     * @maxLength 400
     * @nullable
     */
    name?: string | null
    /** Optional markdown description shown when show_description is enabled. */
    description?: string
    /** Optional react-grid-layout positions keyed by breakpoint (sm, xs). */
    layouts?: _WidgetTileLayoutsOpenApiApi
    /** Whether to show the description on the dashboard tile. */
    show_description?: boolean
    widget_type: SessionReplayListWidgetAddRequestOpenApiApiWidgetType
    /** Configuration for the recent recordings widget. */
    config: SessionReplayListWidgetConfigApi
}

export type AddDashboardWidgetRequestApi =
    | ErrorTrackingListWidgetAddRequestOpenApiApi
    | SessionReplayListWidgetAddRequestOpenApiApi

/**
 * OpenAPI-only batch-add schema with widget_type-discriminated config shapes for agents.
 */
export interface AddDashboardWidgetsBatchRequestOpenApiApi {
    /**
     * Widget tiles to add atomically. Supported widget_type values: error_tracking_list, session_replay_list. Use dashboard-widget-catalog-list for per-type config_schema documentation. (1–10 per request).
     * @minItems 1
     * @maxItems 10
     */
    widgets: AddDashboardWidgetRequestApi[]
}

export interface AddDashboardWidgetsBatchResponseApi {
    /** Created dashboard widget tiles in request order. */
    tiles: DashboardTileApi[]
}

/**
 * * `add` - add
 * * `remove` - remove
 * * `set` - set
 */
export type ActionEnumApi = (typeof ActionEnumApi)[keyof typeof ActionEnumApi]

export const ActionEnumApi = {
    Add: 'add',
    Remove: 'remove',
    Set: 'set',
} as const

export interface BulkUpdateTagsRequestApi {
    /**
     * List of object IDs to update tags on.
     * @maxItems 500
     */
    ids: number[]
    /** 'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.
     *
     * * `add` - add
     * * `remove` - remove
     * * `set` - set */
    action: ActionEnumApi
    /** Tag names to add, remove, or set. */
    tags: string[]
}

export interface BulkUpdateTagsItemApi {
    id: number
    tags: string[]
}

export interface BulkUpdateTagsErrorApi {
    id: number
    reason: string
}

export interface BulkUpdateTagsResponseApi {
    updated: BulkUpdateTagsItemApi[]
    skipped: BulkUpdateTagsErrorApi[]
}

export type ErrorTrackingListWidgetCatalogEntryOpenApiApiWidgetType =
    (typeof ErrorTrackingListWidgetCatalogEntryOpenApiApiWidgetType)[keyof typeof ErrorTrackingListWidgetCatalogEntryOpenApiApiWidgetType]

export const ErrorTrackingListWidgetCatalogEntryOpenApiApiWidgetType = {
    ErrorTrackingList: 'error_tracking_list',
} as const

export interface ErrorTrackingListWidgetCatalogEntryOpenApiApi {
    widget_type: ErrorTrackingListWidgetCatalogEntryOpenApiApiWidgetType
    group_id: string
    group_label: string
    label: string
    description: string
    /** OpenAPI config shape for this widget type (documentation; matches batch-add/PATCH schemas). */
    readonly config_schema: ErrorTrackingListWidgetConfigApi
    /** @nullable */
    required_product_access?: string | null
}

export type SessionReplayListWidgetCatalogEntryOpenApiApiWidgetType =
    (typeof SessionReplayListWidgetCatalogEntryOpenApiApiWidgetType)[keyof typeof SessionReplayListWidgetCatalogEntryOpenApiApiWidgetType]

export const SessionReplayListWidgetCatalogEntryOpenApiApiWidgetType = {
    SessionReplayList: 'session_replay_list',
} as const

export interface SessionReplayListWidgetCatalogEntryOpenApiApi {
    widget_type: SessionReplayListWidgetCatalogEntryOpenApiApiWidgetType
    group_id: string
    group_label: string
    label: string
    description: string
    /** OpenAPI config shape for this widget type (documentation; matches batch-add/PATCH schemas). */
    readonly config_schema: SessionReplayListWidgetConfigApi
    /** @nullable */
    required_product_access?: string | null
}

export type WidgetCatalogEntryApi =
    | ErrorTrackingListWidgetCatalogEntryOpenApiApi
    | SessionReplayListWidgetCatalogEntryOpenApiApi

export interface WidgetCatalogResponseApi {
    /** Registered dashboard widget types available when dashboard-widgets is enabled. */
    results: WidgetCatalogEntryApi[]
}

export interface DataColorThemeApi {
    readonly id: number
    /** @maxLength 100 */
    name: string
    colors?: unknown
    readonly is_global: boolean
    /** @nullable */
    readonly created_at: string | null
    readonly created_by: UserBasicApi
}

export interface PaginatedDataColorThemeListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DataColorThemeApi[]
}

export interface PatchedDataColorThemeApi {
    readonly id?: number
    /** @maxLength 100 */
    name?: string
    colors?: unknown
    readonly is_global?: boolean
    /** @nullable */
    readonly created_at?: string | null
    readonly created_by?: UserBasicApi
}

/**
 * * `error_tracking_list` - error_tracking_list
 */
export type ErrorTrackingListWidgetTypeEnumApi =
    (typeof ErrorTrackingListWidgetTypeEnumApi)[keyof typeof ErrorTrackingListWidgetTypeEnumApi]

export const ErrorTrackingListWidgetTypeEnumApi = {
    ErrorTrackingList: 'error_tracking_list',
} as const

/**
 * * `session_replay_list` - session_replay_list
 */
export type SessionReplayListWidgetTypeEnumApi =
    (typeof SessionReplayListWidgetTypeEnumApi)[keyof typeof SessionReplayListWidgetTypeEnumApi]

export const SessionReplayListWidgetTypeEnumApi = {
    SessionReplayList: 'session_replay_list',
} as const

export type DashboardTemplatesListParams = {
    /**
     * Omit for all templates. When set, filter by featured flag; parsed with str_to_bool (same as other API query booleans).
     */
    is_featured?: boolean
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Optional. When not using `search`, results are sorted with featured templates first (`is_featured=true`), then by `template_name` (case-insensitive A–Z; `-template_name` for Z–A) or by `created_at` (`-created_at` for newest first). When `search` is set, order is featured first, then relevance rank, then case-insensitive name for ties.
     */
    ordering?: string
    /**
     * Optional. `global`: official templates only. `team`: this project's saved templates only (`scope=team` rows for the current project). `feature_flag`: feature-flag dashboard templates only. Omit for both official and this project's templates (default dashboard template picker behavior).
     */
    scope?: DashboardTemplatesListScope
}

export type DashboardTemplatesListScope = (typeof DashboardTemplatesListScope)[keyof typeof DashboardTemplatesListScope]

export const DashboardTemplatesListScope = {
    FeatureFlag: 'feature_flag',
    Global: 'global',
    Team: 'team',
} as const

export type DashboardsListParams = {
    format?: DashboardsListFormat
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Optional. Match against dashboard `name`, `description`, and tag names. Returns case-insensitive substring matches and fuzzy trigram matches (typos, transpositions, prefix-as-you-type) together, ordered exact-first, then pinned status, then name; each result's `search_match_type` is `exact` or `similar`. When omitted, dashboards are ordered by pinned status then alphabetical name. Capped at 200 characters; longer queries return a 400 error.
     */
    search?: string
}

export type DashboardsListFormat = (typeof DashboardsListFormat)[keyof typeof DashboardsListFormat]

export const DashboardsListFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsCreateParams = {
    format?: DashboardsCreateFormat
}

export type DashboardsCreateFormat = (typeof DashboardsCreateFormat)[keyof typeof DashboardsCreateFormat]

export const DashboardsCreateFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsRetrieveParams = {
    /**
     * Object (or pre-encoded JSON string) to override dashboard filters for this request only (not persisted). Top-level keys replace; nested values are not deep-merged — pass the complete value for any key you override. Accepts the same keys as the dashboard filters schema (e.g., `date_from`, `date_to`, `properties`). Ignored when accessed via a sharing token.
     */
    filters_override?: string
    format?: DashboardsRetrieveFormat
    /**
     * Object (or pre-encoded JSON string) to override dashboard variables for this request only (not persisted). Format: {"<variable_id>": {"code_name": "<code_name>", "variableId": "<variable_id>", "value": <new_value>}}. Each entry must include `code_name` — partial entries are silently dropped. The simplest workflow is to call `dashboard-get` first, copy the matching entry from the response, and mutate `value`. Top-level keys replace; nested values are not deep-merged. Ignored when accessed via a sharing token.
     */
    variables_override?: string
}

export type DashboardsRetrieveFormat = (typeof DashboardsRetrieveFormat)[keyof typeof DashboardsRetrieveFormat]

export const DashboardsRetrieveFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsUpdateParams = {
    format?: DashboardsUpdateFormat
}

export type DashboardsUpdateFormat = (typeof DashboardsUpdateFormat)[keyof typeof DashboardsUpdateFormat]

export const DashboardsUpdateFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsPartialUpdateParams = {
    format?: DashboardsPartialUpdateFormat
}

export type DashboardsPartialUpdateFormat =
    (typeof DashboardsPartialUpdateFormat)[keyof typeof DashboardsPartialUpdateFormat]

export const DashboardsPartialUpdateFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsDestroyParams = {
    format?: DashboardsDestroyFormat
}

export type DashboardsDestroyFormat = (typeof DashboardsDestroyFormat)[keyof typeof DashboardsDestroyFormat]

export const DashboardsDestroyFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsCopyTileCreateParams = {
    format?: DashboardsCopyTileCreateFormat
}

export type DashboardsCopyTileCreateFormat =
    (typeof DashboardsCopyTileCreateFormat)[keyof typeof DashboardsCopyTileCreateFormat]

export const DashboardsCopyTileCreateFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsCreateTextTileCreateParams = {
    format?: DashboardsCreateTextTileCreateFormat
}

export type DashboardsCreateTextTileCreateFormat =
    (typeof DashboardsCreateTextTileCreateFormat)[keyof typeof DashboardsCreateTextTileCreateFormat]

export const DashboardsCreateTextTileCreateFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsDeleteTileParams = {
    format?: DashboardsDeleteTileFormat
}

export type DashboardsDeleteTileFormat = (typeof DashboardsDeleteTileFormat)[keyof typeof DashboardsDeleteTileFormat]

export const DashboardsDeleteTileFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsMoveTileCreateParams = {
    format?: DashboardsMoveTileCreateFormat
}

export type DashboardsMoveTileCreateFormat =
    (typeof DashboardsMoveTileCreateFormat)[keyof typeof DashboardsMoveTileCreateFormat]

export const DashboardsMoveTileCreateFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsMoveTilePartialUpdateParams = {
    format?: DashboardsMoveTilePartialUpdateFormat
}

export type DashboardsMoveTilePartialUpdateFormat =
    (typeof DashboardsMoveTilePartialUpdateFormat)[keyof typeof DashboardsMoveTilePartialUpdateFormat]

export const DashboardsMoveTilePartialUpdateFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsReorderTilesCreateParams = {
    format?: DashboardsReorderTilesCreateFormat
}

export type DashboardsReorderTilesCreateFormat =
    (typeof DashboardsReorderTilesCreateFormat)[keyof typeof DashboardsReorderTilesCreateFormat]

export const DashboardsReorderTilesCreateFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsRunInsightsRetrieveParams = {
    /**
     * Object (or pre-encoded JSON string) to override dashboard filters for this request only (not persisted). Top-level keys replace; nested values are not deep-merged — pass the complete value for any key you override. Accepts the same keys as the dashboard filters schema (e.g., `date_from`, `date_to`, `properties`). Ignored when accessed via a sharing token.
     */
    filters_override?: string
    format?: DashboardsRunInsightsRetrieveFormat
    /**
     * 'optimized' (default) returns LLM-friendly formatted text per insight. 'json' returns the raw query result objects.
     */
    output_format?: DashboardsRunInsightsRetrieveOutputFormat
    /**
     * Cache behavior. 'force_cache' (default) serves from cache even if stale. 'blocking' uses cache if fresh, otherwise recalculates. 'force_blocking' always recalculates.
     */
    refresh?: DashboardsRunInsightsRetrieveRefresh
    /**
     * Object (or pre-encoded JSON string) to override dashboard variables for this request only (not persisted). Format: {"<variable_id>": {"code_name": "<code_name>", "variableId": "<variable_id>", "value": <new_value>}}. Each entry must include `code_name` — partial entries are silently dropped. The simplest workflow is to call `dashboard-get` first, copy the matching entry from the response, and mutate `value`. Top-level keys replace; nested values are not deep-merged. Ignored when accessed via a sharing token.
     */
    variables_override?: string
}

export type DashboardsRunInsightsRetrieveFormat =
    (typeof DashboardsRunInsightsRetrieveFormat)[keyof typeof DashboardsRunInsightsRetrieveFormat]

export const DashboardsRunInsightsRetrieveFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsRunInsightsRetrieveOutputFormat =
    (typeof DashboardsRunInsightsRetrieveOutputFormat)[keyof typeof DashboardsRunInsightsRetrieveOutputFormat]

export const DashboardsRunInsightsRetrieveOutputFormat = {
    Json: 'json',
    Optimized: 'optimized',
} as const

export type DashboardsRunInsightsRetrieveRefresh =
    (typeof DashboardsRunInsightsRetrieveRefresh)[keyof typeof DashboardsRunInsightsRetrieveRefresh]

export const DashboardsRunInsightsRetrieveRefresh = {
    Blocking: 'blocking',
    ForceBlocking: 'force_blocking',
    ForceCache: 'force_cache',
} as const

export type DashboardsRunWidgetsRetrieveParams = {
    format?: DashboardsRunWidgetsRetrieveFormat
    /**
     * Comma-separated dashboard tile IDs to run widgets for.
     */
    tile_ids: string
}

export type DashboardsRunWidgetsRetrieveFormat =
    (typeof DashboardsRunWidgetsRetrieveFormat)[keyof typeof DashboardsRunWidgetsRetrieveFormat]

export const DashboardsRunWidgetsRetrieveFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsStreamTilesRetrieveParams = {
    /**
     * Object (or pre-encoded JSON string) to override dashboard filters for this request only (not persisted). Top-level keys replace; nested values are not deep-merged — pass the complete value for any key you override. Accepts the same keys as the dashboard filters schema (e.g., `date_from`, `date_to`, `properties`). Ignored when accessed via a sharing token.
     */
    filters_override?: string
    format?: DashboardsStreamTilesRetrieveFormat
    /**
     * Layout size for tile positioning. 'sm' (default) for standard, 'xs' for mobile. The snake_case alias `layout_size` is also accepted for backward compatibility.
     */
    layoutSize?: DashboardsStreamTilesRetrieveLayoutSize
    /**
     * Object (or pre-encoded JSON string) to override dashboard variables for this request only (not persisted). Format: {"<variable_id>": {"code_name": "<code_name>", "variableId": "<variable_id>", "value": <new_value>}}. Each entry must include `code_name` — partial entries are silently dropped. The simplest workflow is to call `dashboard-get` first, copy the matching entry from the response, and mutate `value`. Top-level keys replace; nested values are not deep-merged. Ignored when accessed via a sharing token.
     */
    variables_override?: string
}

export type DashboardsStreamTilesRetrieveFormat =
    (typeof DashboardsStreamTilesRetrieveFormat)[keyof typeof DashboardsStreamTilesRetrieveFormat]

export const DashboardsStreamTilesRetrieveFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsStreamTilesRetrieveLayoutSize =
    (typeof DashboardsStreamTilesRetrieveLayoutSize)[keyof typeof DashboardsStreamTilesRetrieveLayoutSize]

export const DashboardsStreamTilesRetrieveLayoutSize = {
    Sm: 'sm',
    Xs: 'xs',
} as const

export type DashboardsUpdateTextTileCreateParams = {
    format?: DashboardsUpdateTextTileCreateFormat
}

export type DashboardsUpdateTextTileCreateFormat =
    (typeof DashboardsUpdateTextTileCreateFormat)[keyof typeof DashboardsUpdateTextTileCreateFormat]

export const DashboardsUpdateTextTileCreateFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsWidgetsBatchCreateParams = {
    format?: DashboardsWidgetsBatchCreateFormat
}

export type DashboardsWidgetsBatchCreateFormat =
    (typeof DashboardsWidgetsBatchCreateFormat)[keyof typeof DashboardsWidgetsBatchCreateFormat]

export const DashboardsWidgetsBatchCreateFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsBulkUpdateTagsCreateParams = {
    format?: DashboardsBulkUpdateTagsCreateFormat
}

export type DashboardsBulkUpdateTagsCreateFormat =
    (typeof DashboardsBulkUpdateTagsCreateFormat)[keyof typeof DashboardsBulkUpdateTagsCreateFormat]

export const DashboardsBulkUpdateTagsCreateFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsCreateFromTemplateJsonCreateParams = {
    format?: DashboardsCreateFromTemplateJsonCreateFormat
}

export type DashboardsCreateFromTemplateJsonCreateFormat =
    (typeof DashboardsCreateFromTemplateJsonCreateFormat)[keyof typeof DashboardsCreateFromTemplateJsonCreateFormat]

export const DashboardsCreateFromTemplateJsonCreateFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsCreateUnlistedDashboardCreateParams = {
    format?: DashboardsCreateUnlistedDashboardCreateFormat
}

export type DashboardsCreateUnlistedDashboardCreateFormat =
    (typeof DashboardsCreateUnlistedDashboardCreateFormat)[keyof typeof DashboardsCreateUnlistedDashboardCreateFormat]

export const DashboardsCreateUnlistedDashboardCreateFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DashboardsWidgetCatalogRetrieveParams = {
    format?: DashboardsWidgetCatalogRetrieveFormat
}

export type DashboardsWidgetCatalogRetrieveFormat =
    (typeof DashboardsWidgetCatalogRetrieveFormat)[keyof typeof DashboardsWidgetCatalogRetrieveFormat]

export const DashboardsWidgetCatalogRetrieveFormat = {
    Json: 'json',
    Txt: 'txt',
} as const

export type DataColorThemesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
