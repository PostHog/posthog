import {
    ACTION_TYPE,
    EVENT_TYPE,
    OrganizationMembershipLevel,
    PluginsAccessLevel,
    ShownAsValue,
    RETENTION_RECURRING,
    RETENTION_FIRST_TIME,
    ENTITY_MATCH_TYPE,
    FunnelLayout,
    COHORT_DYNAMIC,
    COHORT_STATIC,
    BinCountAuto,
} from 'lib/constants'
import { PluginConfigSchema } from '@posthog/plugin-scaffold'
import { PluginInstallationType } from 'scenes/plugins/types'
import { Dayjs } from 'dayjs'
import { PROPERTY_MATCH_TYPE } from 'lib/constants'
import { UploadFile } from 'antd/lib/upload/interface'

export type Optional<T, K extends string | number | symbol> = Omit<T, K> & { [K in keyof T]?: T[K] }

export enum AvailableFeature {
    ZAPIER = 'zapier',
    ORGANIZATIONS_PROJECTS = 'organizations_projects',
    GOOGLE_LOGIN = 'google_login',
    SAML = 'saml',
    DASHBOARD_COLLABORATION = 'dashboard_collaboration',
    INGESTION_TAXONOMY = 'ingestion_taxonomy',
}

export interface ColumnConfig {
    active: string[] | 'DEFAULT'
}

export interface UserType {
    uuid: string
    date_joined: string
    first_name: string
    email: string
    email_opt_in: boolean
    events_column_config: ColumnConfig
    anonymize_data: boolean
    distinct_id: string
    toolbar_mode: 'disabled' | 'toolbar'
    has_password: boolean
    is_staff: boolean
    is_impersonated: boolean
    organization: OrganizationType | null
    team: TeamBasicType | null
    organizations: OrganizationBasicType[]
    realm: 'cloud' | 'hosted' | 'hosted-clickhouse'
    posthog_version?: string
}

/* Type for User objects in nested serializers (e.g. created_by) */
export interface UserBasicType {
    id: number
    uuid: string
    distinct_id: string
    first_name: string
    email: string
}

export interface PluginAccess {
    view: boolean
    install: boolean
    configure: boolean
}

export interface PersonalAPIKeyType {
    id: string
    label: string
    value?: string
    created_at: string
    last_used_at: string
    team_id: number
    user_id: string
}

export interface OrganizationBasicType {
    id: string
    name: string
}

export interface OrganizationType extends OrganizationBasicType {
    created_at: string
    updated_at: string
    membership_level: OrganizationMembershipLevel | null
    personalization: PersonalizationData
    setup: SetupState
    setup_section_2_completed: boolean
    plugins_access_level: PluginsAccessLevel
    teams: TeamBasicType[] | null
    available_features: AvailableFeature[]
    domain_whitelist: string[]
    is_member_join_email_enabled: boolean
}

export interface OrganizationMemberType {
    id: string
    user: UserBasicType
    level: OrganizationMembershipLevel
    joined_at: string
    updated_at: string
}

export interface APIErrorType {
    type: 'authentication_error' | 'invalid_request' | 'server_error' | 'throttled_error' | 'validation_error'
    code: string
    detail: string
    attr: string | null
}

export interface EventUsageType {
    event: string
    usage_count: number
    volume: number
}

export interface PropertyUsageType {
    key: string
    usage_count: number
    volume: number
}

export interface TeamBasicType {
    id: number
    uuid: string
    organization: string // Organization ID
    api_token: string
    name: string
    completed_snippet_onboarding: boolean
    ingested_event: boolean
    is_demo: boolean
    timezone: string
}

export interface TeamType extends TeamBasicType {
    anonymize_ips: boolean
    app_urls: string[]
    slack_incoming_webhook: string
    session_recording_opt_in: boolean
    session_recording_retention_period_days: number | null
    test_account_filters: AnyPropertyFilter[]
    data_attributes: string[]
}

export interface ActionType {
    count?: number
    created_at: string
    deleted?: boolean
    id: number
    is_calculating?: boolean
    last_calculated_at?: string
    name: string
    post_to_slack?: boolean
    steps?: ActionStepType[]
    created_by: UserBasicType | null
}

/** Sync with plugin-server/src/types.ts */
export enum ActionStepUrlMatching {
    Contains = 'contains',
    Regex = 'regex',
    Exact = 'exact',
}

export interface ActionStepType {
    event?: string
    href?: string
    id?: number
    name?: string
    properties?: []
    selector?: string
    tag_name?: string
    text?: string
    url?: string
    url_matching?: ActionStepUrlMatching
    isNew?: string
}

export interface ElementType {
    attr_class?: string[]
    attr_id?: string
    attributes: Record<string, string>
    href: string
    nth_child: number
    nth_of_type: number
    order: number
    tag_name: string
    text?: string
}

export type ToolbarUserIntent = 'add-action' | 'edit-action'

export type EditorProps = {
    apiURL?: string
    jsURL?: string
    temporaryToken?: string
    actionId?: number
    userIntent?: ToolbarUserIntent
    instrument?: boolean
    distinctId?: string
    userEmail?: boolean
    dataAttributes?: string[]
    featureFlags?: Record<string, string | boolean>
}

export type PropertyFilterValue = string | number | (string | number)[] | null

export interface PropertyFilter {
    key: string
    operator: PropertyOperator | null
    type: string
    value: PropertyFilterValue
}

export type EmptyPropertyFilter = Partial<PropertyFilter>

export type AnyPropertyFilter = PropertyFilter | EmptyPropertyFilter

/** Sync with plugin-server/src/types.ts */
export enum PropertyOperator {
    Exact = 'exact',
    IsNot = 'is_not',
    IContains = 'icontains',
    NotIContains = 'not_icontains',
    Regex = 'regex',
    NotRegex = 'not_regex',
    GreaterThan = 'gt',
    LessThan = 'lt',
    IsSet = 'is_set',
    IsNotSet = 'is_not_set',
}

export enum SavedInsightsTabs {
    All = 'all',
    Yours = 'yours',
    Favorites = 'favorites',
}

/** Sync with plugin-server/src/types.ts */
interface BasePropertyFilter {
    key: string
    value: PropertyFilterValue
    label?: string
}

/** Sync with plugin-server/src/types.ts */
export interface EventPropertyFilter extends BasePropertyFilter {
    type: 'event'
    operator: PropertyOperator
}

/** Sync with plugin-server/src/types.ts */
export interface PersonPropertyFilter extends BasePropertyFilter {
    type: 'person'
    operator: PropertyOperator
}

/** Sync with plugin-server/src/types.ts */
export interface ElementPropertyFilter extends BasePropertyFilter {
    type: 'element'
    key: 'tag_name' | 'text' | 'href' | 'selector'
    operator: PropertyOperator
}

/** Sync with plugin-server/src/types.ts */
export interface CohortPropertyFilter extends BasePropertyFilter {
    type: 'cohort'
    key: 'id'
    value: number
}

/** Sync with plugin-server/src/types.ts */
export type ActionStepProperties =
    | EventPropertyFilter
    | PersonPropertyFilter
    | ElementPropertyFilter
    | CohortPropertyFilter

export interface RecordingDurationFilter extends BasePropertyFilter {
    type: 'recording'
    key: 'duration'
    value: number
    operator: PropertyOperator
}

interface RecordingNotViewedFilter extends BasePropertyFilter {
    type: 'recording'
    key: 'unseen'
}

export type RecordingPropertyFilter = RecordingDurationFilter | RecordingNotViewedFilter

export interface ActionTypePropertyFilter extends BasePropertyFilter {
    type: typeof ACTION_TYPE
    properties?: Array<EventPropertyFilter>
}

export interface EventTypePropertyFilter extends BasePropertyFilter {
    type: typeof EVENT_TYPE
    properties?: Array<EventPropertyFilter>
}

export type SessionsPropertyFilter =
    | PersonPropertyFilter
    | CohortPropertyFilter
    | RecordingPropertyFilter
    | ActionTypePropertyFilter
    | EventTypePropertyFilter

export type EntityType = 'actions' | 'events' | 'new_entity'

export interface Entity {
    id: string | number
    name: string
    order: number
    type: EntityType
}

export enum EntityTypes {
    ACTIONS = 'actions',
    EVENTS = 'events',
    NEW_ENTITY = 'new_entity',
}

export type EntityFilter = {
    type?: EntityType
    id: Entity['id'] | null
    name: string | null
    index?: number
    order?: number
}

export interface FunnelStepRangeEntityFilter extends EntityFilter {
    funnel_from_step: number
    funnel_to_step: number
}

export interface EntityWithProperties extends Entity {
    properties: Record<string, any>
}

export interface PersonType {
    id?: number
    uuid?: string
    name?: string
    distinct_ids: string[]
    properties: Record<string, any>
    is_identified: boolean
    created_at?: string
}

export interface CohortGroupType {
    id: string
    days?: string
    action_id?: number
    event_id?: string
    label?: string
    count?: number
    count_operator?: string
    properties?: AnyPropertyFilter[]
    matchType: MatchType
}

export type MatchType = typeof ENTITY_MATCH_TYPE | typeof PROPERTY_MATCH_TYPE
export type CohortTypeType = typeof COHORT_STATIC | typeof COHORT_DYNAMIC

export interface CohortType {
    count?: number
    description?: string
    created_by?: UserBasicType | null
    created_at?: string
    deleted?: boolean
    id: number | 'new' | 'personsModalNew'
    is_calculating?: boolean
    last_calculation?: string
    is_static?: boolean
    name?: string
    csv?: UploadFile
    groups: CohortGroupType[]
}

export interface InsightHistory {
    id: number
    filters: Record<string, any>
    name?: string
    createdAt: string
    saved: boolean
    type: ViewType
}

export interface SavedFunnel extends InsightHistory {
    created_by: string
}

export type BinCountValue = number | typeof BinCountAuto

// https://github.com/PostHog/posthog/blob/master/posthog/constants.py#L106
export enum StepOrderValue {
    STRICT = 'strict',
    UNORDERED = 'unordered',
    ORDERED = 'ordered',
}

export enum PersonsTabType {
    EVENTS = 'events',
    SESSIONS = 'sessions',
}

export enum LayoutView {
    Card = 'card',
    List = 'list',
}

export interface EventType {
    elements: ElementType[]
    elements_hash: string | null
    event: string
    id: number | string
    properties: Record<string, any>
    timestamp: string
    person?: Partial<PersonType> | null
}

export interface EventFormattedType {
    event: EventType
    date_break?: Dayjs
    new_events?: boolean
}

export interface SessionType {
    distinct_id: string
    global_session_id: string
    length: number
    start_time: string
    end_time: string
    session_recordings: SessionRecordingType[]
    start_url: string | null
    end_url: string | null
    email?: string | null
    matching_events: Array<number | string>
}

export interface SessionRecordingType {
    id: string
    /** Whether this recording has been viewed already. */
    viewed: boolean
    /** Length of recording in seconds. */
    recording_duration: number
    /** When the recording starts in ISO format. */
    start_time: string
    /** When the recording ends in ISO format. */
    end_time: string
}

export interface BillingType {
    should_setup_billing: boolean
    is_billing_active: boolean
    plan: PlanInterface | null
    billing_period_ends: string
    event_allocation: number | null
    current_usage: number | null
    subscription_url: string
    current_bill_amount: number | null
    should_display_current_bill: boolean
}

export interface PlanInterface {
    key: string
    name: string
    custom_setup_billing_message: string
    image_url: string
    self_serve: boolean
    is_metered_billing: boolean
    event_allowance: number
    price_string: string
}

export interface DashboardItemType {
    id: number
    name: string
    short_id: string
    description?: string
    filters: Record<string, any>
    filters_hash: string
    order: number
    deleted: boolean
    saved: boolean
    created_at: string
    layouts: Record<string, any>
    color: string | null
    last_refresh: string
    refreshing: boolean
    created_by: UserBasicType | null
    is_sample: boolean
    dashboard: number
    dive_dashboard?: number
    result: any | null
    updated_at: string
    tags: string[]
}

export interface DashboardType {
    id: number
    name: string
    description: string
    pinned: boolean
    items: DashboardItemType[]
    created_at: string
    created_by: UserBasicType | null
    is_shared: boolean
    share_token: string
    deleted: boolean
    filters: Record<string, any>
    creation_mode: 'default' | 'template' | 'duplicate'
    tags: string[]
}

export type DashboardLayoutSize = 'lg' | 'sm' | 'xs' | 'xxs'

export interface OrganizationInviteType {
    id: string
    target_email: string
    first_name: string
    is_expired: boolean
    emailing_attempt_made: boolean
    created_by: UserBasicType | null
    created_at: string
    updated_at: string
}

export interface PluginType {
    id: number
    plugin_type: PluginInstallationType
    name: string
    description?: string
    url?: string
    tag?: string
    latest_tag?: string
    config_schema: Record<string, PluginConfigSchema> | PluginConfigSchema[]
    source?: string
    maintainer?: string
    is_global: boolean
    organization_id: string
    organization_name: string
    metrics?: Record<string, StoredMetricMathOperations>
    capabilities?: Record<'jobs' | 'methods' | 'scheduled_tasks', string[]>
    public_jobs?: Record<string, JobSpec>
}

export interface JobPayloadFieldOptions {
    type: 'string' | 'boolean' | 'json' | 'number' | 'date'
    required?: boolean
}

export interface JobSpec {
    payload?: Record<string, JobPayloadFieldOptions>
}
export interface PluginConfigType {
    id?: number
    plugin: number
    team_id: number
    enabled: boolean
    order: number
    config: Record<string, any>
    error?: PluginErrorType
}

export interface PluginErrorType {
    message: string
    time: string
    stack?: string
    name?: string
    event?: Record<string, any>
}

export enum PluginLogEntryType {
    Debug = 'DEBUG',
    Log = 'LOG',
    Info = 'INFO',
    Warn = 'WARN',
    Error = 'ERROR',
}

export interface PluginLogEntry {
    id: string
    team_id: number
    plugin_id: number
    plugin_config_id: number
    timestamp: string
    type: PluginLogEntryType
    is_system: boolean
    message: string
    instance_id: string
}

export enum AnnotationScope {
    DashboardItem = 'dashboard_item',
    Project = 'project',
    Organization = 'organization',
}

export interface AnnotationType {
    id: string
    scope: AnnotationScope
    content: string
    date_marker: string
    created_by?: UserBasicType | 'local' | null
    created_at: string
    updated_at: string
    dashboard_item?: number
    deleted?: boolean
    creation_type?: string
}

export enum ChartDisplayType {
    ActionsLineGraphLinear = 'ActionsLineGraph',
    ActionsLineGraphCumulative = 'ActionsLineGraphCumulative',
    ActionsTable = 'ActionsTable',
    ActionsPieChart = 'ActionsPie',
    ActionsBarChart = 'ActionsBar',
    ActionsBarChartValue = 'ActionsBarValue',
    PathsViz = 'PathsViz',
    FunnelViz = 'FunnelViz',
}

export type ShownAsType = ShownAsValue // DEPRECATED: Remove when releasing `remove-shownas`
export type BreakdownType = 'cohort' | 'person' | 'event'
export type IntervalType = 'minute' | 'hour' | 'day' | 'week' | 'month'

// NB! Keep InsightType and ViewType in sync!
export type InsightType = 'TRENDS' | 'SESSIONS' | 'FUNNELS' | 'RETENTION' | 'PATHS' | 'LIFECYCLE' | 'STICKINESS'

export enum ViewType {
    TRENDS = 'TRENDS',
    STICKINESS = 'STICKINESS',
    LIFECYCLE = 'LIFECYCLE',
    SESSIONS = 'SESSIONS',
    FUNNELS = 'FUNNELS',
    RETENTION = 'RETENTION',
    PATHS = 'PATHS',
    // Views that are not insights:
    HISTORY = 'HISTORY',
}

export enum PathType {
    PageView = '$pageview',
    Screen = '$screen',
    CustomEvent = 'custom_event',
}

export enum FunnelVizType {
    Steps = 'steps',
    TimeToConvert = 'time_to_convert',
    Trends = 'trends',
}

export type RetentionType = typeof RETENTION_RECURRING | typeof RETENTION_FIRST_TIME

export type BreakdownKeyType = string | number | (string | number)[] | null

export interface FilterType {
    insight?: InsightType
    display?: ChartDisplayType
    interval?: IntervalType
    date_from?: string | null
    date_to?: string | null
    properties?: PropertyFilter[]
    events?: Record<string, any>[]
    actions?: Record<string, any>[]
    breakdown_type?: BreakdownType | null
    breakdown?: BreakdownKeyType
    breakdown_value?: string | number
    shown_as?: ShownAsType
    session?: string
    period?: string
    retentionType?: RetentionType
    new_entity?: Record<string, any>[]
    returning_entity?: Record<string, any>
    target_entity?: Record<string, any>
    path_type?: PathType
    start_point?: string | number
    stickiness_days?: number
    type?: EntityType
    entity_id?: string | number
    entity_type?: EntityType
    entity_math?: string
    people_day?: any
    people_action?: any
    formula?: any
    filter_test_accounts?: boolean
    from_dashboard?: boolean | number
    layout?: FunnelLayout // used only for funnels
    funnel_step?: number
    entrance_period_start?: string // this and drop_off is used for funnels time conversion date for the persons modal
    drop_off?: boolean
    funnel_viz_type?: string // parameter sent to funnels API for time conversion code path
    funnel_from_step?: number // used in time to convert: initial step index to compute time to convert
    funnel_to_step?: number // used in time to convert: ending step index to compute time to convert
    funnel_step_breakdown?: string | number[] | number | null // used in steps breakdown: persons modal
    compare?: boolean
    bin_count?: BinCountValue // used in time to convert: number of bins to show in histogram
    funnel_window_interval_unit?: FunnelConversionWindowTimeUnit // minutes, days, weeks, etc. for conversion window
    funnel_window_interval?: number | undefined // length of conversion window
    funnel_order_type?: StepOrderValue
    exclusions?: FunnelStepRangeEntityFilter[] // used in funnel exclusion filters
}

export interface SystemStatusSubrows {
    columns: string[]
    rows: string[][]
}

export interface SystemStatusRow {
    metric: string
    value: string
    key?: string
    description?: string
    subrows?: SystemStatusSubrows
}

export interface SystemStatus {
    overview: SystemStatusRow[]
    internal_metrics: {
        clickhouse?: {
            id: number
            share_token: string
        }
    }
}

export type QuerySummary = { duration: string } & Record<string, string>

export interface SystemStatusQueriesResult {
    postgres_running: QuerySummary[]
    clickhouse_running?: QuerySummary[]
    clickhouse_slow_log?: QuerySummary[]
}

export interface SystemStatusAnalyzeResult {
    query: string
    timing: {
        query_id: string
        event_time: string
        query_duration_ms: number
        read_rows: number
        read_size: string
        result_rows: number
        result_size: string
        memory_usage: string
    }
    flamegraphs: Record<string, string>
}

export type PersonalizationData = Record<string, string | string[] | null>

interface EnabledSetupState {
    is_active: true // Whether the onbarding setup is currently active
    current_section: number
    any_project_ingested_events: boolean
    any_project_completed_snippet_onboarding: boolean
    non_demo_team_id: number | null
    has_invited_team_members: boolean
}

interface DisabledSetupState {
    is_active: false
    current_section: null
}

export type SetupState = EnabledSetupState | DisabledSetupState

export interface ActionFilter extends EntityFilter {
    math?: string
    math_property?: string
    properties: PropertyFilter[]
    type: EntityType
}

export interface TrendResult {
    action: ActionFilter
    count: number
    data: number[]
    days: string[]
    dates?: string[]
    label: string
    labels: string[]
    breakdown_value?: string | number
    aggregated_value: number
    status?: string
}

export interface TrendResultWithAggregate extends TrendResult {
    aggregated_value: number
}

export interface FunnelStep {
    // The type returned from the API.
    action_id: string
    average_conversion_time: number | null
    count: number
    name: string
    order: number
    people?: string[]
    type: EntityType
    labels?: string[]
    breakdown?: BreakdownKeyType
    breakdown_value?: string | number
}

export interface FunnelStepWithNestedBreakdown extends FunnelStep {
    nested_breakdown?: FunnelStep[]
}

export interface FunnelResult<ResultType = FunnelStep[] | FunnelsTimeConversionBins> {
    is_cached: boolean
    last_refresh: string | null
    result: ResultType
    type: 'Funnel'
}

export interface FunnelsTimeConversionBins {
    bins: [number, number][]
    average_conversion_time: number
    steps: FunnelStep[] | FunnelStep[][]
}

export interface FunnelTimeConversionMetrics {
    averageTime: number
    stepRate: number
    totalRate: number
}

export interface FunnelConversionWindow {
    funnel_window_interval_unit?: FunnelConversionWindowTimeUnit
    funnel_window_interval?: number | undefined
}

// https://github.com/PostHog/posthog/blob/master/posthog/models/filters/mixins/funnel.py#L100
export enum FunnelConversionWindowTimeUnit {
    Minute = 'minute',
    Hour = 'hour',
    Day = 'day',
    Week = 'week',
    Month = 'month',
}

export interface FunnelRequestParams extends FilterType {
    refresh?: boolean
    from_dashboard?: boolean | number
    funnel_window_days?: number
}

export interface LoadedRawFunnelResults {
    results: FunnelStep[] | FunnelStep[][] | FunnelsTimeConversionBins
    filters: Partial<FilterType>
}

export interface FunnelStepWithConversionMetrics extends FunnelStep {
    droppedOffFromPrevious: number
    conversionRates: {
        fromPrevious: number
        total: number
        fromBasisStep: number // either fromPrevious or total, depending on FunnelStepReference
    }
    nested_breakdown?: Omit<FunnelStepWithConversionMetrics, 'nested_breakdown'>[]
}

export interface FlattenedFunnelStep extends FunnelStepWithConversionMetrics {
    rowKey: number | string
    isBreakdownParent?: boolean
    breakdownIndex?: number
}

export interface ChartParams {
    dashboardItemId?: number
    color?: string
    filters: Partial<FilterType>
    inSharedMode?: boolean
    showPersonsModal?: boolean
    cachedResults?: TrendResult
    view: ViewType
}

export interface FeatureFlagGroupType {
    properties: AnyPropertyFilter[]
    rollout_percentage: number | null
}

export interface MultivariateFlagVariant {
    key: string
    name: string | null
    rollout_percentage: number
}

export interface MultivariateFlagOptions {
    variants: MultivariateFlagVariant[]
}

interface FeatureFlagFilters {
    groups: FeatureFlagGroupType[]
    multivariate: MultivariateFlagOptions | null
}

export interface FeatureFlagType {
    id: number | null
    key: string
    name: string // Used as description
    filters: FeatureFlagFilters
    deleted: boolean
    active: boolean
    created_by: UserBasicType | null
    created_at: string
    is_simple_flag: boolean
    rollout_percentage: number | null
}

export interface FeatureFlagOverrideType {
    id: number
    feature_flag: number
    user: number
    override_value: boolean | string
}

export interface CombinedFeatureFlagAndOverrideType {
    feature_flag: FeatureFlagType
    value_for_user_without_override: boolean | string
    override: FeatureFlagOverrideType | null
}

export interface PrevalidatedInvite {
    id: string
    target_email: string
    first_name: string
    organization_name: string
}

interface AuthBackends {
    'google-oauth2'?: boolean
    gitlab?: boolean
    github?: boolean
    saml?: boolean
}

export interface PreflightStatus {
    // Attributes that accept undefined values (i.e. `?`) are not received when unauthenticated
    django: boolean
    plugins: boolean
    redis: boolean
    db: boolean
    /** An initiated instance is one that already has any organization(s). */
    initiated: boolean
    /** Org creation is allowed on Cloud OR initiated self-hosted organizations with a license and MULTI_ORG_ENABLED. */
    can_create_org: boolean
    /** Whether this is PostHog Cloud. */
    cloud: boolean
    celery: boolean
    /** Whether EE code is available (but not necessarily a license). */
    ee_available?: boolean
    /** Is ClickHouse used as the analytics database instead of Postgres. */
    is_clickhouse_enabled?: boolean
    realm: 'cloud' | 'hosted' | 'hosted-clickhouse'
    db_backend?: 'postgres' | 'clickhouse'
    available_social_auth_providers: AuthBackends
    available_timezones?: Record<string, number>
    opt_out_capture?: boolean
    posthog_version?: string
    email_service_available?: boolean
    /** Whether PostHog is running in DEBUG mode. */
    is_debug?: boolean
    is_event_property_usage_enabled?: boolean
    licensed_users_available?: number | null
    site_url?: string
}

export enum ItemMode { // todo: consolidate this and dashboardmode
    Edit = 'edit',
    View = 'view',
}

export enum DashboardMode { // Default mode is null
    Edit = 'edit', // When the dashboard is being edited
    Fullscreen = 'fullscreen', // When the dashboard is on full screen (presentation) mode
    Sharing = 'sharing', // When the sharing configuration is opened
    Public = 'public', // When viewing the dashboard publicly via a shareToken
    Internal = 'internal', // When embedded into another page (e.g. /instance/status)
}

export enum DashboardItemMode {
    Edit = 'edit',
}

// Reserved hotkeys globally available
export type GlobalHotKeys = 'g'

// Hotkeys for local (component) actions
export type HotKeys =
    | 'a'
    | 'b'
    | 'c'
    | 'd'
    | 'e'
    | 'f'
    | 'h'
    | 'i'
    | 'j'
    | 'k'
    | 'l'
    | 'm'
    | 'n'
    | 'o'
    | 'p'
    | 'q'
    | 'r'
    | 's'
    | 't'
    | 'u'
    | 'v'
    | 'w'
    | 'x'
    | 'y'
    | 'z'
    | 'escape'

export interface LicenseType {
    id: number
    key: string
    plan: string
    valid_until: string
    max_users: string | null
    created_at: string
}

export interface EventDefinition {
    id: string
    name: string
    description: string
    tags?: string[]
    volume_30_day: number | null
    query_usage_30_day: number | null
    owner?: UserBasicType | null
    updated_at?: string
    updated_by?: UserBasicType | null
}

export interface PropertyDefinition {
    id: string
    name: string
    description: string
    tags?: string[]
    volume_30_day: number | null
    query_usage_30_day: number | null
    updated_at?: string
    updated_by?: UserBasicType | null
    is_numerical?: boolean // Marked as optional to allow merge of EventDefinition & PropertyDefinition
}

export interface PersonProperty {
    name: string
    count: number
}

export interface SelectOption {
    value: string
    label?: string
}

export interface SelectOptionWithChildren extends SelectOption {
    children: React.ReactChildren
    ['data-attr']: string
    key: string
}

export interface KeyMapping {
    label: string
    description: string | JSX.Element
    examples?: string[]
    hide?: boolean
}

export interface TileParams {
    title: string
    targetPath: string
    openInNewTab?: boolean
    hoverText?: string
    icon: JSX.Element
    class?: string
}

export interface TiledIconModuleProps {
    tiles: TileParams[]
    header?: string
    subHeader?: string
    analyticsModuleKey?: string
}

export type EventOrPropType = EventDefinition & PropertyDefinition

export interface AppContext {
    current_user: UserType | null
    preflight: PreflightStatus
    default_event_name: string
    persisted_feature_flags?: string[]
}

export type StoredMetricMathOperations = 'max' | 'min' | 'sum'
