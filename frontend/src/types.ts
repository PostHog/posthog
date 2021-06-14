import {
    ACTION_TYPE,
    EVENT_TYPE,
    OrganizationMembershipLevel,
    PluginsAccessLevel,
    ShownAsValue,
    RETENTION_RECURRING,
    RETENTION_FIRST_TIME,
} from 'lib/constants'
import { PluginConfigSchema } from '@posthog/plugin-scaffold'
import { PluginInstallationType } from 'scenes/plugins/types'
import { ViewType } from 'scenes/insights/insightLogic'
import { Dayjs } from 'dayjs'

export type Optional<T, K extends string | number | symbol> = Omit<T, K> & { [K in keyof T]?: T[K] }

export type AvailableFeatures =
    | 'zapier'
    | 'organizations_projects'
    | 'google_login'
    | 'dashboard_collaboration'
    | 'clickhouse'
    | 'ingestion_taxonomy'

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
    available_features: AvailableFeatures[]
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
    test_account_filters: FilterType[]
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
}

export interface PropertyFilter {
    key: string
    operator: string | null
    type: string
    value: string | number | (string | number)[]
}

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

/** Sync with plugin-server/src/types.ts */
interface BasePropertyFilter {
    key: string
    value: string | number | Array<string | number> | null
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
    days?: string
    action_id?: number
    properties?: Record<string, any>
}

export interface CohortType {
    count?: number
    created_by?: UserBasicType | null
    created_at?: string
    deleted?: boolean
    id: number | 'new'
    is_calculating?: boolean
    last_calculation?: string
    is_static?: boolean
    name?: string
    csv?: File
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
    event_count: number
    events?: EventType[]
    global_session_id: string
    length: number
    start_time: string
    end_time: string
    session_recordings: Array<{ id: string; viewed: boolean }>
    start_url?: string
    end_url?: string
    email?: string
    matching_events: Array<number | string>
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
    result: any | null
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

export type DisplayType =
    | 'ActionsLineGraph'
    | 'ActionsLineGraphCumulative'
    | 'ActionsTable'
    | 'ActionsPie'
    | 'ActionsBar'
    | 'ActionsBarValue'
    | 'PathsViz'
    | 'FunnelViz'
export type InsightType = 'TRENDS' | 'SESSIONS' | 'FUNNELS' | 'RETENTION' | 'PATHS' | 'LIFECYCLE' | 'STICKINESS'
export type ShownAsType = ShownAsValue // DEPRECATED: Remove when releasing `remove-shownas`
export type BreakdownType = 'cohort' | 'person' | 'event'

export enum PathType {
    PageView = '$pageview',
    AutoCapture = '$autocapture',
    Screen = '$screen',
    CustomEvent = 'custom_event',
}

export type RetentionType = typeof RETENTION_RECURRING | typeof RETENTION_FIRST_TIME

export interface FilterType {
    insight?: InsightType
    display?: DisplayType
    interval?: string
    date_from?: string
    date_to?: string
    properties?: PropertyFilter[]
    events?: Record<string, any>[]
    actions?: Record<string, any>[]
    breakdown_type?: BreakdownType
    breakdown?: string
    breakdown_value?: string
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
    entity_id?: string | number
    entity_type?: EntityType
    entity_math?: string
    people_day?: any
    people_action?: any
    formula?: any
    filter_test_accounts?: boolean
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
    label: string
    labels: string[]
    breakdown_value?: string | number
    aggregated_value: number
    status?: string
}

export interface TrendResultWithAggregate extends TrendResult {
    aggregated_value: number
}

export interface ChartParams {
    dashboardItemId?: number
    color?: string
    filters?: Partial<FilterType>
    inSharedMode?: boolean
    cachedResults?: TrendResult
    view: ViewType
}

export interface FeatureFlagGroupType {
    properties: PropertyFilter[]
    rollout_percentage: number | null
}
interface FeatureFlagFilters {
    groups: FeatureFlagGroupType[]
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
}

export interface PreflightStatus {
    // Attributes that accept undefined values (i.e. `?`) are not received when unauthenticated
    django: boolean
    plugins: boolean
    redis: boolean
    db: boolean
    initiated: boolean
    cloud: boolean
    celery: boolean
    ee_available?: boolean
    is_clickhouse_enabled?: boolean
    db_backend?: 'postgres' | 'clickhouse'
    available_social_auth_providers: AuthBackends
    available_timezones?: Record<string, number>
    opt_out_capture?: boolean
    posthog_version?: string
    email_service_available?: boolean
    is_debug?: boolean
    is_event_property_usage_enabled?: boolean
    licensed_users_available?: number | null
    site_url?: string
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
    tags: string[]
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
    tags: string[]
    volume_30_day: number | null
    query_usage_30_day: number | null
    owner?: UserBasicType | null
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
}
