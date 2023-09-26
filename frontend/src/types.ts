import {
    BIN_COUNT_AUTO,
    DashboardPrivilegeLevel,
    DashboardRestrictionLevel,
    ENTITY_MATCH_TYPE,
    FunnelLayout,
    OrganizationMembershipLevel,
    PluginsAccessLevel,
    PROPERTY_MATCH_TYPE,
    RETENTION_FIRST_TIME,
    RETENTION_RECURRING,
    ShownAsValue,
    TeamMembershipLevel,
} from 'lib/constants'
import { PluginConfigSchema } from '@posthog/plugin-scaffold'
import { PluginInstallationType } from 'scenes/plugins/types'
import { UploadFile } from 'antd/lib/upload/interface'
import { eventWithTime } from '@rrweb/types'
import { PostHog } from 'posthog-js'
import { PopoverProps } from 'lib/lemon-ui/Popover/Popover'
import { Dayjs, dayjs } from 'lib/dayjs'
import { ChartDataset, ChartType, InteractionItem } from 'chart.js'
import { LogLevel } from 'rrweb'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { BehavioralFilterKey, BehavioralFilterType } from 'scenes/cohorts/CohortFilters/types'
import { LogicWrapper } from 'kea'
import { AggregationAxisFormat } from 'scenes/insights/aggregationAxisFormat'
import { Layout } from 'react-grid-layout'
import {
    DatabaseSchemaQueryResponseField,
    HogQLQuery,
    InsightQueryNode,
    InsightVizNode,
    Node,
    QueryContext,
} from './queries/schema'
import { JSONContent } from 'scenes/notebooks/Notebook/utils'
import { DashboardCompatibleScenes } from 'lib/components/SceneDashboardChoice/sceneDashboardChoiceModalLogic'

export type Optional<T, K extends string | number | symbol> = Omit<T, K> & { [K in keyof T]?: T[K] }

// Keep this in sync with backend constants (constants.py)
export enum AvailableFeature {
    EVENTS = 'events',
    TRACKED_USERS = 'tracked_users',
    DATA_RETENTION = 'data_retention',
    SUBSCRIPTIONS = 'subscriptions',
    DASHBOARD_COLLABORATION = 'dashboard_collaboration',
    DASHBOARD_PERMISSIONING = 'dashboard_permissioning',
    INGESTION_TAXONOMY = 'ingestion_taxonomy',
    PATHS_ADVANCED = 'paths_advanced',
    CORRELATION_ANALYSIS = 'correlation_analysis',
    GROUP_ANALYTICS = 'group_analytics',
    TAGGING = 'tagging',
    BEHAVIORAL_COHORT_FILTERING = 'behavioral_cohort_filtering',
    SESSION_RECORDINGS = 'session_recordings',
    RECORDINGS_PLAYLISTS = 'recordings_playlists',
    RECORDINGS_PERFORMANCE = 'recordings_performance',
    RECORDINGS_FILE_EXPORT = 'recordings_file_export',
    BOOLEAN_FLAGS = 'boolean_flags',
    MULTIVARIATE_FLAGS = 'multivariate_flags',
    EXPERIMENTATION = 'experimentation',
    APPS = 'apps',
    SLACK_INTEGRATION = 'slack_integration',
    MICROSOFT_TEAMS_INTEGRATION = 'microsoft_teams_integration',
    DISCORD_INTEGRATION = 'discord_integration',
    ZAPIER = 'zapier',
    APP_METRICS = 'app_metrics',
    TEAM_MEMBERS = 'team_members',
    API_ACCESS = 'api_access',
    ORGANIZATIONS_PROJECTS = 'organizations_projects',
    PROJECT_BASED_PERMISSIONING = 'project_based_permissioning',
    ROLE_BASED_ACCESS = 'role_based_access',
    GOOGLE_LOGIN = 'google_login',
    SAML = 'saml',
    SSO_ENFORCEMENT = 'sso_enforcement',
    WHITE_LABELLING = 'white_labelling',
    COMMUNITY_SUPPORT = 'community_support',
    DEDICATED_SUPPORT = 'dedicated_support',
    EMAIL_SUPPORT = 'email_support',
    ACCOUNT_MANAGER = 'account_manager',
    TRAINING = 'training',
    CONFIGURATION_SUPPORT = 'configuration_support',
    TERMS_AND_CONDITIONS = 'terms_and_conditions',
    SECURITY_ASSESSMENT = 'security_assessment',
    BESPOKE_PRICING = 'bespoke_pricing',
    INVOICE_PAYMENTS = 'invoice_payments',
    SUPPORT_SLAS = 'support_slas',
}

export type AvailableProductFeature = {
    key: AvailableFeature
    name: string
    description?: string | null
    limit?: number | null
    note?: string | null
    unit?: string | null
}

export enum ProductKey {
    COHORTS = 'cohorts',
    ACTIONS = 'actions',
    EXPERIMENTS = 'experiments',
    FEATURE_FLAGS = 'feature_flags',
    ANNOTATIONS = 'annotations',
    HISTORY = 'history',
    INGESTION_WARNINGS = 'ingestion_warnings',
    PERSONS = 'persons',
    SURVEYS = 'surveys',
    SESSION_REPLAY = 'session_replay',
    DATA_WAREHOUSE = 'data_warehouse',
    DATA_WAREHOUSE_SAVED_QUERY = 'data_warehouse_saved_queries',
    EARLY_ACCESS_FEATURES = 'early_access_features',
    PRODUCT_ANALYTICS = 'product_analytics',
}

export enum LicensePlan {
    Scale = 'scale',
    Enterprise = 'enterprise',
}

export enum Realm {
    Cloud = 'cloud',
    Demo = 'demo',
    SelfHostedPostgres = 'hosted',
    SelfHostedClickHouse = 'hosted-clickhouse',
}

export enum Region {
    US = 'US',
    EU = 'EU',
}

export type SSOProvider = 'google-oauth2' | 'github' | 'gitlab' | 'saml'

export interface AuthBackends {
    'google-oauth2'?: boolean
    gitlab?: boolean
    github?: boolean
}

export type ColumnChoice = string[] | 'DEFAULT'

export interface ColumnConfig {
    active: ColumnChoice
}

interface UserBaseType {
    uuid: string
    distinct_id: string
    first_name: string
    email: string
}

/* Type for User objects in nested serializers (e.g. created_by) */
export interface UserBasicType extends UserBaseType {
    is_email_verified?: any
    id: number
}

/**
 * A user can have scene dashboard choices for multiple teams
 * TODO does this only have the current team's choices?
 */
export interface SceneDashboardChoice {
    scene: DashboardCompatibleScenes
    dashboard: number | DashboardBasicType
}

/** Full User model. */
export interface UserType extends UserBaseType {
    date_joined: string
    email_opt_in: boolean
    notification_settings: NotificationSettings
    events_column_config: ColumnConfig
    anonymize_data: boolean
    toolbar_mode: 'disabled' | 'toolbar'
    has_password: boolean
    is_staff: boolean
    is_impersonated: boolean
    organization: OrganizationType | null
    team: TeamBasicType | null
    organizations: OrganizationBasicType[]
    realm?: Realm
    is_email_verified?: boolean | null
    pending_email?: string | null
    is_2fa_enabled: boolean
    has_social_auth: boolean
    has_seen_product_intro_for?: Record<string, boolean>
    scene_personalisation?: SceneDashboardChoice[]
}

export interface NotificationSettings {
    plugin_disabled: boolean
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
    slug: string
    membership_level: OrganizationMembershipLevel | null
}

interface OrganizationMetadata {
    instance_tag?: string
}

export interface OrganizationType extends OrganizationBasicType {
    created_at: string
    updated_at: string
    plugins_access_level: PluginsAccessLevel
    teams: TeamBasicType[] | null
    available_features: AvailableFeature[]
    available_product_features: AvailableProductFeature[]
    is_member_join_email_enabled: boolean
    customer_id: string | null
    enforce_2fa: boolean | null
    metadata?: OrganizationMetadata
}

export interface OrganizationDomainType {
    id: string
    domain: string
    is_verified: boolean
    verified_at: string // Datetime
    verification_challenge: string
    jit_provisioning_enabled: boolean
    sso_enforcement: SSOProvider | ''
    has_saml: boolean
    saml_entity_id: string
    saml_acs_url: string
    saml_x509_cert: string
}

/** Member properties relevant at both organization and project level. */
export interface BaseMemberType {
    id: string
    user: UserBasicType
    joined_at: string
    updated_at: string
    is_2fa_enabled: boolean
    has_social_auth: boolean
}

export interface OrganizationMemberType extends BaseMemberType {
    /** Level at which the user is in the organization. */
    level: OrganizationMembershipLevel
    is_2fa_enabled: boolean
    has_social_auth: boolean
}

export interface ExplicitTeamMemberType extends BaseMemberType {
    /** Level at which the user explicitly is in the project. */
    level: TeamMembershipLevel
    /** Level at which the user is in the organization. */
    parent_level: OrganizationMembershipLevel
    /** Effective level of the user within the project, which may be higher than parent level, but not lower. */
    effective_level: OrganizationMembershipLevel
}

/**
 * While OrganizationMemberType and ExplicitTeamMemberType refer to actual Django models,
 * this interface is only used in the frontend for fusing the data from these models together.
 */
export interface FusedTeamMemberType extends BaseMemberType {
    /**
     * Level at which the user explicitly is in the project.
     * Null means that membership is implicit (when showing permitted members)
     * or that there's no membership at all (when showing addable members).
     */
    explicit_team_level: TeamMembershipLevel | null
    /** Level at which the user is in the organization. */
    organization_level: OrganizationMembershipLevel
    /** Effective level of the user within the project. */
    level: OrganizationMembershipLevel
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
    has_completed_onboarding_for?: Record<string, boolean>
    ingested_event: boolean
    is_demo: boolean
    timezone: string
    /** Whether the project is private. */
    access_control: boolean
}

export interface CorrelationConfigType {
    excluded_person_property_names?: string[]
    excluded_event_property_names?: string[]
    excluded_event_names?: string[]
}

export interface TeamType extends TeamBasicType {
    created_at: string
    updated_at: string
    anonymize_ips: boolean
    app_urls: string[]
    recording_domains: string[]
    slack_incoming_webhook: string
    autocapture_opt_out: boolean
    session_recording_opt_in: boolean
    capture_console_log_opt_in: boolean
    capture_performance_opt_in: boolean
    autocapture_exceptions_opt_in: boolean
    surveys_opt_in?: boolean
    autocapture_exceptions_errors_to_ignore: string[]
    test_account_filters: AnyPropertyFilter[]
    test_account_filters_default_checked: boolean
    /** 0 or unset for Sunday, 1 for Monday. */
    week_start_day?: number
    path_cleaning_filters: PathCleaningFilter[]
    data_attributes: string[]
    person_display_name_properties: string[]
    has_group_types: boolean
    primary_dashboard: number // Dashboard shown on the project homepage
    live_events_columns: string[] | null // Custom columns shown on the Live Events page

    /** Effective access level of the user in this specific team. Null if user has no access. */
    effective_membership_level: OrganizationMembershipLevel | null

    /** Used to exclude person properties from correlation analysis results.
     *
     * For example can be used to exclude properties that have trivial causation.
     * This field should have a default value of `{}`, but it IS nullable and can be `null` in some cases.
     */
    correlation_config: CorrelationConfigType | null
    person_on_events_querying_enabled: boolean
    groups_on_events_querying_enabled: boolean
    extra_settings?: Record<string, string | number | boolean | undefined>
}

// This type would be more correct without `Partial<TeamType>`, but it's only used in the shared dashboard/insight
// scenes, so not worth the refactor to use the `isAuthenticatedTeam()` check
export type TeamPublicType = Partial<TeamType> & Pick<TeamType, 'id' | 'uuid' | 'name' | 'timezone'>

export interface ActionType {
    count?: number
    created_at: string
    deleted?: boolean
    id: number
    is_calculating?: boolean
    last_calculated_at?: string
    last_updated_at?: string // alias for last_calculated_at to achieve event and action parity
    name: string | null
    description?: string
    post_to_slack?: boolean
    slack_message_format?: string
    steps?: ActionStepType[]
    created_by: UserBasicType | null
    tags?: string[]
    verified?: boolean
    is_action?: true
    action_id?: number // alias of id to make it compatible with event definitions uuid
    bytecode?: any[]
    bytecode_error?: string
}

/** Sync with plugin-server/src/types.ts */
export enum StringMatching {
    Contains = 'contains',
    Regex = 'regex',
    Exact = 'exact',
}

export interface ActionStepType {
    event?: string | null
    id?: number
    name?: string
    properties?: AnyPropertyFilter[]
    selector?: string | null
    /** @deprecated Only `selector` should be used now. */
    tag_name?: string
    text?: string | null
    /** @default StringMatching.Exact */
    text_matching?: StringMatching | null
    href?: string | null
    /** @default StringMatching.Exact */
    href_matching?: StringMatching | null
    url?: string | null
    /** @default StringMatching.Contains */
    url_matching?: StringMatching | null
    isNew?: string
}

export interface ElementType {
    attr_class?: string[]
    attr_id?: string
    attributes: Record<string, string>
    href?: string
    nth_child?: number
    nth_of_type?: number
    order?: number
    tag_name: string
    text?: string
}

export type ToolbarUserIntent = 'add-action' | 'edit-action'
export type ToolbarSource = 'url' | 'localstorage'
export type ToolbarVersion = 'toolbar'

/* sync with posthog-js */
export interface ToolbarParams {
    apiURL?: string
    jsURL?: string
    token?: string /** public posthog-js token */
    temporaryToken?: string /** private temporary user token */
    actionId?: number
    userIntent?: ToolbarUserIntent
    source?: ToolbarSource
    toolbarVersion?: ToolbarVersion
    instrument?: boolean
    distinctId?: string
    userEmail?: string
    dataAttributes?: string[]
    featureFlags?: Record<string, string | boolean>
}

export interface ToolbarProps extends ToolbarParams {
    posthog?: PostHog
    disableExternalStyles?: boolean
}

export type PathCleaningFilter = { alias?: string; regex?: string }

export type PropertyFilterValue = string | number | (string | number)[] | null

/** Sync with plugin-server/src/types.ts */
export enum PropertyOperator {
    Exact = 'exact',
    IsNot = 'is_not',
    IContains = 'icontains',
    NotIContains = 'not_icontains',
    Regex = 'regex',
    NotRegex = 'not_regex',
    GreaterThan = 'gt',
    GreaterThanOrEqual = 'gte',
    LessThan = 'lt',
    LessThanOrEqual = 'lte',
    IsSet = 'is_set',
    IsNotSet = 'is_not_set',
    IsDateExact = 'is_date_exact',
    IsDateBefore = 'is_date_before',
    IsDateAfter = 'is_date_after',
    Between = 'between',
    NotBetween = 'not_between',
    Minimum = 'min',
    Maximum = 'max',
}

export enum SavedInsightsTabs {
    All = 'all',
    Yours = 'yours',
    Favorites = 'favorites',
    History = 'history',
}

export enum ReplayTabs {
    Recent = 'recent',
    Playlists = 'playlists',
    FilePlayback = 'file-playback',
}

export enum ExperimentsTabs {
    All = 'all',
    Yours = 'yours',
    Archived = 'archived',
}

export enum ProgressStatus {
    Draft = 'draft',
    Running = 'running',
    Complete = 'complete',
}

export enum PropertyFilterType {
    /** Event metadata and fields on the clickhouse events table */
    Meta = 'meta',
    /** Event properties */
    Event = 'event',
    /** Person properties */
    Person = 'person',
    Element = 'element',
    /** Event property with "$feature/" prepended */
    Feature = 'feature',
    Session = 'session',
    Cohort = 'cohort',
    Recording = 'recording',
    Group = 'group',
    HogQL = 'hogql',
}

/** Sync with plugin-server/src/types.ts */
interface BasePropertyFilter {
    key: string
    value?: PropertyFilterValue
    label?: string
    type?: PropertyFilterType
}

/** Sync with plugin-server/src/types.ts */
export interface EventPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Event
    operator: PropertyOperator
}

/** Sync with plugin-server/src/types.ts */
export interface PersonPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Person
    operator: PropertyOperator
}

/** Sync with plugin-server/src/types.ts */
export interface ElementPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Element
    key: 'tag_name' | 'text' | 'href' | 'selector'
    operator: PropertyOperator
}

export interface SessionPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Session
    key: '$session_duration'
    operator: PropertyOperator
}

/** Sync with plugin-server/src/types.ts */
export interface CohortPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Cohort
    key: 'id'
    value: number
}

export interface GroupPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Group
    group_type_index?: number | null
    operator: PropertyOperator
}

export interface FeaturePropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.Feature
    operator: PropertyOperator
}

export interface HogQLPropertyFilter extends BasePropertyFilter {
    type: PropertyFilterType.HogQL
    key: string
}

export interface EmptyPropertyFilter {
    type?: never
    value?: never
    operator?: never
    key?: never
}

export type AnyPropertyFilter =
    | EventPropertyFilter
    | PersonPropertyFilter
    | ElementPropertyFilter
    | SessionPropertyFilter
    | CohortPropertyFilter
    | RecordingDurationFilter
    | GroupPropertyFilter
    | FeaturePropertyFilter
    | HogQLPropertyFilter
    | EmptyPropertyFilter

export type AnyFilterLike = AnyPropertyFilter | PropertyGroupFilter | PropertyGroupFilterValue

export type SessionRecordingId = SessionRecordingType['id']

export interface RRWebRecordingConsoleLogPayload {
    level: LogLevel
    payload: (string | null)[]
    trace: string[]
}

export interface RRWebRecordingNetworkPayload {
    [key: number]: any
}

export interface RecordingConsoleLogBase {
    parsedPayload: string
    hash?: string // md5() on parsedPayload. Used for deduping console logs.
    count?: number // Number of duplicate console logs
    previewContent?: React.ReactNode // Content to show in first line
    fullContent?: React.ReactNode // Full content to show when item is expanded
    traceContent?: React.ReactNode // Url content to show on right side
    rawString: string // Raw text used for fuzzy search
    level: LogLevel
}

export type RecordingConsoleLog = RecordingConsoleLogBase & RecordingTimeMixinType

export type RecordingConsoleLogV2 = {
    timestamp: number
    windowId: string | undefined
    level: LogLevel
    content: string
    lines: string[]
    trace: string[]
    count: number
}

export interface RecordingSegment {
    kind: 'window' | 'buffer' | 'gap'
    startTimestamp: number // Epoch time that the segment starts
    endTimestamp: number // Epoch time that the segment ends
    durationMs: number
    windowId?: string
    isActive: boolean
}

export type EncodedRecordingSnapshot = {
    windowId: string
    data: eventWithTime[]
}

export interface SessionRecordingSnapshotSource {
    source: 'blob' | 'realtime'
    start_timestamp?: string
    end_timestamp?: string
    blob_key?: string
    loaded: boolean
}

export interface SessionRecordingSnapshotResponse {
    // Future interface
    sources?: SessionRecordingSnapshotSource[]
    snapshots?: EncodedRecordingSnapshot[]

    // legacy interface
    next?: string
    // When loaded from S3
    blob_keys?: string[]
    // When loaded from Clickhouse (legacy)
    snapshot_data_by_window_id?: Record<string, eventWithTime[]>
}

export type RecordingSnapshot = eventWithTime & {
    windowId: string
}

export interface SessionPlayerSnapshotData {
    snapshots?: RecordingSnapshot[]
    sources?: SessionRecordingSnapshotSource[]
    next?: string
    blob_keys?: string[]
}

export interface SessionPlayerData {
    pinnedCount: number
    person: PersonType | null
    segments: RecordingSegment[]
    bufferedToTime: number | null
    snapshotsByWindowId: Record<string, eventWithTime[]>
    durationMs: number
    start?: Dayjs
    end?: Dayjs
    fullyLoaded: boolean
}

export enum SessionRecordingUsageType {
    VIEWED = 'viewed',
    ANALYZED = 'analyzed',
    LOADED = 'loaded',
}

export enum SessionRecordingPlayerTab {
    ALL = 'all',
    EVENTS = 'events',
    CONSOLE = 'console',
    NETWORK = 'network',
}

export enum SessionPlayerState {
    READY = 'ready',
    BUFFER = 'buffer',
    PLAY = 'play',
    PAUSE = 'pause',
    SCRUB = 'scrub',
    SKIP = 'skip',
    ERROR = 'error',
}

export type AutoplayDirection = 'newer' | 'older' | null

/** Sync with plugin-server/src/types.ts */
export type ActionStepProperties =
    | EventPropertyFilter
    | PersonPropertyFilter
    | ElementPropertyFilter
    | CohortPropertyFilter

export interface RecordingDurationFilter extends BasePropertyFilter {
    type: PropertyFilterType.Recording
    key: 'duration'
    value: number
    operator: PropertyOperator
}

export type DurationType = 'duration' | 'active_seconds' | 'inactive_seconds'

export type FilterableLogLevel = 'log' | 'warn' | 'error'
export interface RecordingFilters {
    date_from?: string | null
    date_to?: string | null
    events?: FilterType['events']
    actions?: FilterType['actions']
    properties?: AnyPropertyFilter[]
    session_recording_duration?: RecordingDurationFilter
    duration_type_filter?: DurationType
    console_logs?: FilterableLogLevel[]
    filter_test_accounts?: boolean
}

export interface LocalRecordingFilters extends RecordingFilters {
    new_entity?: Record<string, any>[]
}

export interface SessionRecordingsResponse {
    results: SessionRecordingType[]
    has_next: boolean
}

export type EntityType = 'actions' | 'events' | 'new_entity'

export interface Entity {
    id: string | number
    name: string
    custom_name?: string
    order: number
    type: EntityType
}

export enum EntityTypes {
    ACTIONS = 'actions',
    EVENTS = 'events',
}

export type EntityFilter = {
    type?: EntityType
    id: Entity['id'] | null
    name?: string | null
    custom_name?: string | null
    index?: number
    order?: number
}

export interface FunnelExclusion extends Partial<EntityFilter> {
    funnel_from_step?: number
    funnel_to_step?: number
}

export type EntityFilterTypes = EntityFilter | ActionFilter | null

export interface PersonType {
    id?: string
    uuid?: string
    name?: string
    distinct_ids: string[]
    properties: Record<string, any>
    created_at?: string
    is_identified?: boolean
}

export interface PersonListParams {
    properties?: AnyPropertyFilter[]
    search?: string
    cohort?: number
    distinct_id?: string
    include_total?: boolean // PostHog 3000-only
}

export interface MatchedRecordingEvent {
    uuid: string
}

export interface MatchedRecording {
    session_id?: string
    events: MatchedRecordingEvent[]
}

interface CommonActorType {
    id: string | number
    properties: Record<string, any>
    created_at: string
    matched_recordings: MatchedRecording[]
    value_at_data_point: number | null
}

export interface PersonActorType extends CommonActorType {
    type: 'person'
    /** Serial ID (NOT UUID). */
    id: number
    uuid: string
    name?: string
    distinct_ids: string[]
    is_identified: boolean
}

export interface GroupActorType extends CommonActorType {
    type: 'group'
    /** Group key. */
    id: string
    group_key: string
    group_type_index: number
}

export type ActorType = PersonActorType | GroupActorType

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
    name?: string
}

// Synced with `posthog/models/property.py`
export interface CohortCriteriaType {
    id: string // Criteria filter id
    key: string
    value: BehavioralFilterType
    type: BehavioralFilterKey
    operator?: PropertyOperator | null
    group_type_index?: number | null
    event_type?: TaxonomicFilterGroupType | null
    operator_value?: PropertyFilterValue
    time_value?: number | string | null
    time_interval?: TimeUnitType | null
    total_periods?: number | null
    min_periods?: number | null
    seq_event_type?: TaxonomicFilterGroupType | null
    seq_event?: string | number | null
    seq_time_value?: number | string | null
    seq_time_interval?: TimeUnitType | null
    negation?: boolean
    value_property?: string | null // Transformed into 'value' for api calls
}

export type EmptyCohortGroupType = Partial<CohortGroupType>

export type EmptyCohortCriteriaType = Partial<CohortCriteriaType>

export type AnyCohortGroupType = CohortGroupType | EmptyCohortGroupType

export type AnyCohortCriteriaType = CohortCriteriaType | EmptyCohortCriteriaType

export type MatchType = typeof ENTITY_MATCH_TYPE | typeof PROPERTY_MATCH_TYPE

export interface CohortType {
    count?: number
    description?: string
    created_by?: UserBasicType | null
    created_at?: string
    deleted?: boolean
    id: number | 'new'
    is_calculating?: boolean
    errors_calculating?: number
    last_calculation?: string
    is_static?: boolean
    name?: string
    csv?: UploadFile
    groups: CohortGroupType[] // To be deprecated once `filter` takes over
    filters: {
        properties: CohortCriteriaGroupFilter
    }
}

export interface InsightHistory {
    id: number
    filters: Record<string, any>
    name?: string
    createdAt: string
    saved: boolean
    type: InsightType
}

export interface SavedFunnel extends InsightHistory {
    created_by: string
}

export type BinCountValue = number | typeof BIN_COUNT_AUTO

// https://github.com/PostHog/posthog/blob/master/posthog/constants.py#L106
export enum StepOrderValue {
    STRICT = 'strict',
    UNORDERED = 'unordered',
    ORDERED = 'ordered',
}

export enum PersonsTabType {
    EVENTS = 'events',
    SESSION_RECORDINGS = 'sessionRecordings',
    PROPERTIES = 'properties',
    COHORTS = 'cohorts',
    RELATED = 'related',
    HISTORY = 'history',
    FEATURE_FLAGS = 'featureFlags',
    DASHBOARD = 'dashboard',
}

export enum LayoutView {
    Card = 'card',
    List = 'list',
}

export interface EventsTableAction {
    name: string
    id: string
}

export interface EventsTableRowItem {
    event?: EventType
    date_break?: string
    new_events?: boolean
}

export interface EventType {
    // fields from the API
    id: string
    distinct_id: string
    properties: Record<string, any>
    event: string
    timestamp: string
    person?: Pick<PersonType, 'is_identified' | 'distinct_ids' | 'properties'>
    elements: ElementType[]
    elements_chain?: string | null
    uuid?: string
}

export interface RecordingTimeMixinType {
    playerTime: number | null
}

export interface RecordingEventType
    extends Pick<EventType, 'id' | 'event' | 'properties' | 'timestamp' | 'elements'>,
        RecordingTimeMixinType {
    fullyLoaded: boolean
}

export interface SessionRecordingPlaylistType {
    /** The primary key in the database, used as well in API endpoints */
    id: number
    short_id: string
    name: string
    derived_name?: string | null
    description?: string
    pinned?: boolean
    deleted: boolean
    created_at: string
    created_by: UserBasicType | null
    last_modified_at: string
    last_modified_by: UserBasicType | null
    filters?: RecordingFilters
}

export interface SessionRecordingSegmentType {
    start_time: string
    end_time: string
    window_id: string
    is_active: boolean
}

export interface SessionRecordingType {
    id: string
    /** Whether this recording has been viewed already. */
    viewed: boolean
    /** Length of recording in seconds. */
    recording_duration: number
    active_seconds?: number
    inactive_seconds?: number
    /** When the recording starts in ISO format. */
    start_time: string
    /** When the recording ends in ISO format. */
    end_time: string
    /** List of matching events. **/
    matching_events?: MatchedRecording[]
    distinct_id?: string
    email?: string
    person?: PersonType
    click_count?: number
    keypress_count?: number
    /** count of all mouse activity in the recording, not just clicks */
    mouse_activity_count?: number
    start_url?: string
    /** Count of number of playlists this recording is pinned to. **/
    pinned_count?: number
    console_log_count?: number
    console_warn_count?: number
    console_error_count?: number
    /** Where this recording information was loaded from  */
    storage?: 'object_storage_lts' | 'clickhouse' | 'object_storage'
}

export interface SessionRecordingPropertiesType {
    id: string
    properties?: Record<string, any>
}

export interface PerformancePageView {
    session_id: string
    pageview_id: string
    timestamp: string
}
export interface RecentPerformancePageView extends PerformancePageView {
    page_url: string
    duration: number
}

export interface PerformanceEvent {
    uuid: string
    timestamp: string | number
    distinct_id: string
    session_id: string
    window_id: string
    pageview_id: string
    current_url: string

    // BASE_EVENT_COLUMNS
    time_origin?: string
    entry_type?: string
    name?: string

    // RESOURCE_EVENT_COLUMNS
    start_time?: number
    duration?: number
    redirect_start?: number
    redirect_end?: number
    worker_start?: number
    fetch_start?: number
    domain_lookup_start?: number
    domain_lookup_end?: number
    connect_start?: number
    secure_connection_start?: number
    connect_end?: number
    request_start?: number
    response_start?: number
    response_end?: number
    decoded_body_size?: number
    encoded_body_size?: number

    initiator_type?: string
    next_hop_protocol?: string
    render_blocking_status?: string
    response_status?: number
    transfer_size?: number

    // LARGEST_CONTENTFUL_PAINT_EVENT_COLUMNS
    largest_contentful_paint_element?: string
    largest_contentful_paint_render_time?: number
    largest_contentful_paint_load_time?: number
    largest_contentful_paint_size?: number
    largest_contentful_paint_id?: string
    largest_contentful_paint_url?: string

    // NAVIGATION_EVENT_COLUMNS
    dom_complete?: number
    dom_content_loaded_event?: number
    dom_interactive?: number
    load_event_end?: number
    load_event_start?: number
    redirect_count?: number
    navigation_type?: string
    unload_event_end?: number
    unload_event_start?: number

    // Performance summary fields calculated on frontend
    first_contentful_paint?: number // https://web.dev/fcp/
    time_to_interactive?: number // https://web.dev/tti/
    total_blocking_time?: number // https://web.dev/tbt/
}

export interface CurrentBillCycleType {
    current_period_start: number
    current_period_end: number
}

export interface BillingV2FeatureType {
    key: string
    name: string
    description?: string
    unit?: string
    limit?: number
    note?: string
    group?: AvailableFeature
}

export interface BillingV2TierType {
    flat_amount_usd: string
    unit_amount_usd: string
    current_amount_usd: string | null
    current_usage: number
    projected_usage: number | null
    projected_amount_usd: string | null
    up_to: number | null
}

export interface BillingProductV2Type {
    type: string
    usage_key: string
    name: string
    description: string
    price_description?: string | null
    image_url?: string | null
    docs_url: string | null
    free_allocation?: number
    subscribed: boolean
    tiers?: BillingV2TierType[] | null
    tiered: boolean
    current_usage?: number
    projected_amount_usd?: string
    projected_usage?: number
    percentage_usage: number
    current_amount_usd_before_addons: string | null
    current_amount_usd: string | null
    usage_limit: number | null
    has_exceeded_limit: boolean
    unit: string
    unit_amount_usd: string | null
    plans: BillingV2PlanType[]
    contact_support: boolean
    inclusion_only: any
    feature_groups: {
        // deprecated, remove after removing the billing plans table
        group: string
        name: string
        features: BillingV2FeatureType[]
    }[]
    addons: BillingProductV2AddonType[]

    // addons-only: if this addon is included with the base product and not subscribed individually. for backwards compatibility.
    included_with_main_product?: boolean
}

export interface BillingProductV2AddonType {
    name: string
    description: string
    price_description: string | null
    image_url: string | null
    docs_url: string | null
    type: string
    tiers: BillingV2TierType[] | null
    tiered: boolean
    subscribed: boolean
    // sometimes addons are included with the base product, but they aren't subscribed individually
    included_with_main_product?: boolean
    contact_support?: boolean
    unit: string | null
    unit_amount_usd: string | null
    current_amount_usd: string | null
    current_usage: number
    projected_usage: number | null
    projected_amount_usd: string | null
    plans: BillingV2PlanType[]
    usage_key: string
    free_allocation?: number
    percentage_usage?: number
}
export interface BillingV2Type {
    customer_id: string
    has_active_subscription: boolean
    free_trial_until?: Dayjs
    stripe_portal_url?: string
    deactivated?: boolean
    current_total_amount_usd?: string
    current_total_amount_usd_after_discount?: string
    products: BillingProductV2Type[]

    custom_limits_usd?: {
        [key: string]: string | null | undefined
    }
    billing_period?: {
        current_period_start: Dayjs
        current_period_end: Dayjs
        interval: 'month' | 'year'
    }
    license?: {
        plan: LicensePlan
    }
    available_plans?: BillingV2PlanType[]
    discount_percent?: number
    discount_amount_usd?: string
    amount_off_expires_at?: Dayjs
}

export interface BillingV2PlanType {
    free_allocation?: number
    features: BillingV2FeatureType[]
    key: string
    name: string
    description: string
    is_free?: boolean
    products: BillingProductV2Type[]
    plan_key?: string
    current_plan?: any
    tiers?: BillingV2TierType[]
    included_if?: 'no_active_subscription' | 'has_subscription' | null
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

// Creating a nominal type: https://github.com/microsoft/TypeScript/issues/202#issuecomment-961853101
export type InsightShortId = string & { readonly '': unique symbol }

export enum InsightColor {
    White = 'white',
    Black = 'black',
    Blue = 'blue',
    Green = 'green',
    Purple = 'purple',
}

export interface Cacheable {
    last_refresh: string | null
    next_allowed_client_refresh?: string | null
}

export interface TileLayout extends Omit<Layout, 'i'> {
    i?: string // we use `i` in the front end but not in the API
}

export interface Tileable {
    layouts: Record<DashboardLayoutSize, TileLayout> | Record<string, never> // allow an empty object or one with DashboardLayoutSize keys
    color: InsightColor | null
}

export interface DashboardTile extends Tileable, Cacheable {
    id: number
    insight?: InsightModel
    text?: TextModel
    deleted?: boolean
    is_cached?: boolean
}

export interface DashboardTileBasicType {
    id: number
    dashboard_id: number
    deleted?: boolean
}

export interface TextModel {
    body: string
    created_by?: UserBasicType
    last_modified_by?: UserBasicType
    last_modified_at: string
}

export interface InsightModel extends Cacheable {
    /** The unique key we use when communicating with the user, e.g. in URLs */
    short_id: InsightShortId
    /** The primary key in the database, used as well in API endpoints */
    id: number
    name: string
    derived_name?: string | null
    description?: string
    favorited?: boolean
    order: number | null
    result: any | null
    deleted: boolean
    saved: boolean
    created_at: string
    created_by: UserBasicType | null
    is_sample: boolean
    /** @deprecated Use `dashboard_tiles instead */
    dashboards: number[] | null
    dashboard_tiles: DashboardTileBasicType[] | null
    updated_at: string
    tags?: string[]
    last_modified_at: string
    last_modified_by: UserBasicType | null
    effective_restriction_level: DashboardRestrictionLevel
    effective_privilege_level: DashboardPrivilegeLevel
    timezone?: string | null
    /** Only used in the frontend to store the next breakdown url */
    next?: string
    /** Only used in the frontend to toggle showing Baseline in funnels or not */
    disable_baseline?: boolean
    filters: Partial<FilterType>
    query?: Node | null
}

export interface DashboardBasicType {
    id: number
    name: string
    description: string
    pinned: boolean
    created_at: string
    created_by: UserBasicType | null
    is_shared: boolean
    deleted: boolean
    creation_mode: 'default' | 'template' | 'duplicate'
    restriction_level: DashboardRestrictionLevel
    effective_restriction_level: DashboardRestrictionLevel
    effective_privilege_level: DashboardPrivilegeLevel
    tags?: string[]
    /** Purely local value to determine whether the dashboard should be highlighted, e.g. as a fresh duplicate. */
    _highlight?: boolean
}

export interface DashboardTemplateListParams {
    scope?: DashboardTemplateScope
}

export type DashboardTemplateScope = 'team' | 'global' | 'feature_flag'

export interface DashboardType extends DashboardBasicType {
    tiles: DashboardTile[]
    filters: Record<string, any>
}

export interface DashboardTemplateType {
    id: string
    team_id?: number
    created_at?: string
    template_name: string
    dashboard_description?: string
    dashboard_filters?: Record<string, JsonType>
    tiles: DashboardTile[]
    variables?: DashboardTemplateVariableType[]
    tags?: string[]
    image_url?: string
    scope?: DashboardTemplateScope
}

export interface MonacoMarker {
    message: string
}

// makes the DashboardTemplateType properties optional and the tiles properties optional
export type DashboardTemplateEditorType = Partial<Omit<DashboardTemplateType, 'tiles'>> & {
    tiles: Partial<DashboardTile>[]
}

export interface DashboardTemplateVariableType {
    id: string
    name: string
    description: string
    type: 'event'
    default: Record<string, JsonType>
    required: boolean
}

export type DashboardLayoutSize = 'sm' | 'xs'

/** Explicit dashboard collaborator, based on DashboardPrivilege. */
export interface DashboardCollaboratorType {
    id: string
    dashboard_id: DashboardType['id']
    user: UserBasicType
    level: DashboardPrivilegeLevel
    added_at: string
    updated_at: string
}

/** Explicit (dashboard privilege) OR implicit (project admin) dashboard collaborator. */
export type FusedDashboardCollaboratorType = Pick<DashboardCollaboratorType, 'user' | 'level'>

export interface OrganizationInviteType {
    id: string
    target_email: string
    first_name: string
    is_expired: boolean
    emailing_attempt_made: boolean
    created_by: UserBasicType | null
    created_at: string
    updated_at: string
    message?: string
}

export interface PluginType {
    id: number
    plugin_type: PluginInstallationType
    name: string
    description?: string
    url?: string
    tag?: string
    icon?: string
    latest_tag?: string
    config_schema: Record<string, PluginConfigSchema> | PluginConfigSchema[]
    source?: string
    maintainer?: string
    is_global: boolean
    organization_id: string
    organization_name: string
    metrics?: Record<string, StoredMetricMathOperations>
    capabilities?: Record<'jobs' | 'methods' | 'scheduled_tasks', string[] | undefined>
    public_jobs?: Record<string, JobSpec>
}

/** Config passed to app component and logic as props. Sent in Django's app context */
export interface FrontendAppConfig {
    pluginId: number
    pluginConfigId: number
    pluginType: PluginInstallationType | null
    name: string
    url: string
    config: Record<string, any>
}

/** Frontend app created after receiving a bundle via import('').getFrontendApp() */
export interface FrontendApp {
    id: number
    pluginId: number
    error?: any
    title?: string
    logic?: LogicWrapper
    component?: (props: FrontendAppConfig) => JSX.Element
    onInit?: (props: FrontendAppConfig) => void
}

export interface JobPayloadFieldOptions {
    type: 'string' | 'boolean' | 'json' | 'number' | 'date' | 'daterange'
    title?: string
    required?: boolean
    default?: any
    staff_only?: boolean
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
    delivery_rate_24h?: number | null
    created_at?: string
}

export interface PluginConfigWithPluginInfo extends PluginConfigType {
    id: number
    plugin_info: PluginType
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
    Insight = 'dashboard_item',
    Project = 'project',
    Organization = 'organization',
}

export interface RawAnnotationType {
    id: number
    scope: AnnotationScope
    content: string | null
    date_marker: string | null
    created_by?: UserBasicType | null
    created_at: string
    updated_at: string
    dashboard_item?: number | null
    insight_short_id?: InsightModel['short_id'] | null
    insight_name?: InsightModel['name'] | null
    deleted?: boolean
    creation_type?: 'USR' | 'GIT'
}

export interface AnnotationType extends Omit<RawAnnotationType, 'created_at' | 'date_marker'> {
    date_marker: dayjs.Dayjs | null
    created_at: dayjs.Dayjs
}

export interface DatedAnnotationType extends Omit<AnnotationType, 'date_marker'> {
    date_marker: dayjs.Dayjs
}

export enum ChartDisplayType {
    ActionsLineGraph = 'ActionsLineGraph',
    ActionsLineGraphCumulative = 'ActionsLineGraphCumulative',
    ActionsAreaGraph = 'ActionsAreaGraph',
    ActionsTable = 'ActionsTable',
    ActionsPie = 'ActionsPie',
    ActionsBar = 'ActionsBar',
    ActionsBarValue = 'ActionsBarValue',
    WorldMap = 'WorldMap',
    BoldNumber = 'BoldNumber',
}

export type BreakdownType = 'cohort' | 'person' | 'event' | 'group' | 'session' | 'hogql'
export type IntervalType = 'hour' | 'day' | 'week' | 'month'
export type SmoothingType = number

export enum InsightType {
    TRENDS = 'TRENDS',
    STICKINESS = 'STICKINESS',
    LIFECYCLE = 'LIFECYCLE',
    FUNNELS = 'FUNNELS',
    RETENTION = 'RETENTION',
    PATHS = 'PATHS',
    JSON = 'JSON',
    SQL = 'SQL',
}

export enum PathType {
    PageView = '$pageview',
    Screen = '$screen',
    CustomEvent = 'custom_event',
    HogQL = 'hogql',
}

export enum FunnelPathType {
    before = 'funnel_path_before_step',
    between = 'funnel_path_between_steps',
    after = 'funnel_path_after_step',
}

export enum FunnelVizType {
    Steps = 'steps',
    TimeToConvert = 'time_to_convert',
    Trends = 'trends',
}

export type RetentionType = typeof RETENTION_RECURRING | typeof RETENTION_FIRST_TIME

export enum RetentionPeriod {
    Hour = 'Hour',
    Day = 'Day',
    Week = 'Week',
    Month = 'Month',
}

export type BreakdownKeyType = string | number | (string | number)[] | null

export interface Breakdown {
    property: string | number
    type: BreakdownType
    normalize_url?: boolean
}

export interface FilterType {
    // used by all
    from_dashboard?: boolean | number
    insight?: InsightType
    filter_test_accounts?: boolean
    properties?: AnyPropertyFilter[] | PropertyGroupFilter
    sampling_factor?: number | null

    date_from?: string | null
    date_to?: string | null
    /**
     * Whether the `date_from` and `date_to` should be used verbatim. Disables rounding to the start and end of period.
     * Strings are cast to bools, e.g. "true" -> true.
     */
    explicit_date?: boolean | string | null

    events?: Record<string, any>[]
    actions?: Record<string, any>[]
    new_entity?: Record<string, any>[]

    // persons modal
    entity_id?: string | number
    entity_type?: EntityType
    entity_math?: string

    // used by trends and stickiness
    interval?: IntervalType
    // TODO: extract into TrendsFunnelsCommonFilterType
    breakdown_type?: BreakdownType | null
    breakdown?: BreakdownKeyType
    breakdown_normalize_url?: boolean
    breakdowns?: Breakdown[]
    breakdown_group_type_index?: number | null
    aggregation_group_type_index?: number // Groups aggregation
}

export interface PropertiesTimelineFilterType {
    date_from?: string | null // DateMixin
    date_to?: string | null // DateMixin
    interval?: IntervalType // IntervalMixin
    properties?: AnyPropertyFilter[] | PropertyGroupFilter // PropertyMixin
    events?: Record<string, any>[] // EntitiesMixin
    actions?: Record<string, any>[] // EntitiesMixin
    aggregation_group_type_index?: number // GroupsAggregationMixin
    display?: ChartDisplayType // DisplayDerivedMixin
    breakdown_type?: BreakdownType | null
    breakdown?: BreakdownKeyType
}

export interface TrendsFilterType extends FilterType {
    // Specifies that we want to smooth the aggregation over the specified
    // number of intervals, e.g. for a day interval, we may want to smooth over
    // 7 days to remove weekly variation. Smoothing is performed as a moving average.
    smoothing_intervals?: number
    compare?: boolean
    formula?: string
    shown_as?: ShownAsValue
    display?: ChartDisplayType
    breakdown_histogram_bin_count?: number // trends breakdown histogram bin count

    // frontend only
    show_legend?: boolean // used to show/hide legend next to insights graph
    hidden_legend_keys?: Record<string, boolean | undefined> // used to toggle visibilities in table and legend
    aggregation_axis_format?: AggregationAxisFormat // a fixed format like duration that needs calculation
    aggregation_axis_prefix?: string // a prefix to add to the aggregation axis e.g. £
    aggregation_axis_postfix?: string // a postfix to add to the aggregation axis e.g. %
    show_values_on_series?: boolean
    show_percent_stack_view?: boolean
}

export interface StickinessFilterType extends FilterType {
    compare?: boolean
    shown_as?: ShownAsValue
    display?: ChartDisplayType

    // frontend only
    show_legend?: boolean // used to show/hide legend next to insights graph
    hidden_legend_keys?: Record<string, boolean | undefined> // used to toggle visibilities in table and legend
    show_values_on_series?: boolean

    // persons only
    stickiness_days?: number
}

export interface FunnelsFilterType extends FilterType {
    funnel_viz_type?: FunnelVizType // parameter sent to funnels API for time conversion code path
    funnel_from_step?: number // used in time to convert: initial step index to compute time to convert
    funnel_to_step?: number // used in time to convert: ending step index to compute time to convert
    breakdown_attribution_type?: BreakdownAttributionType // funnels breakdown attribution type
    breakdown_attribution_value?: number // funnels breakdown attribution specific step value
    bin_count?: BinCountValue // used in time to convert: number of bins to show in histogram
    funnel_window_interval_unit?: FunnelConversionWindowTimeUnit // minutes, days, weeks, etc. for conversion window
    funnel_window_interval?: number | undefined // length of conversion window
    funnel_order_type?: StepOrderValue
    exclusions?: FunnelExclusion[] // used in funnel exclusion filters
    funnel_aggregate_by_hogql?: string

    // frontend only
    layout?: FunnelLayout // used only for funnels
    funnel_step_reference?: FunnelStepReference // whether conversion shown in graph should be across all steps or just from the previous step
    hidden_legend_keys?: Record<string, boolean | undefined> // used to toggle visibilities in table and legend

    // persons only
    entrance_period_start?: string // this and drop_off is used for funnels time conversion date for the persons modal
    drop_off?: boolean
    funnel_step?: number
    funnel_step_breakdown?: string | number[] | number | null // used in steps breakdown: persons modal
    funnel_custom_steps?: number[] // used to provide custom steps for which to get people in a funnel - primarily for correlation use
    funnel_correlation_person_entity?: Record<string, any> // Funnel Correlation Persons Filter
    funnel_correlation_person_converted?: 'true' | 'false' // Funnel Correlation Persons Converted - success or failure counts
}
export interface PathsFilterType extends FilterType {
    path_type?: PathType
    paths_hogql_expression?: string
    include_event_types?: PathType[]
    start_point?: string
    end_point?: string
    path_groupings?: string[]
    funnel_paths?: FunnelPathType
    funnel_filter?: Record<string, any> // Funnel Filter used in Paths
    exclude_events?: string[] // Paths Exclusion type
    step_limit?: number // Paths Step Limit
    path_replacements?: boolean
    local_path_cleaning_filters?: PathCleaningFilter[]
    edge_limit?: number | undefined // Paths edge limit
    min_edge_weight?: number | undefined // Paths
    max_edge_weight?: number | undefined // Paths

    // persons only
    path_start_key?: string // Paths People Start Key
    path_end_key?: string // Paths People End Key
    path_dropoff_key?: string // Paths People Dropoff Key
}
export interface RetentionFilterType extends FilterType {
    retention_type?: RetentionType
    retention_reference?: 'total' | 'previous' // retention wrt cohort size or previous period
    total_intervals?: number // retention total intervals
    returning_entity?: Record<string, any>
    target_entity?: Record<string, any>
    period?: RetentionPeriod
}
export interface LifecycleFilterType extends FilterType {
    shown_as?: ShownAsValue

    // frontend only
    show_values_on_series?: boolean
    toggledLifecycles?: LifecycleToggle[]
}

export type LifecycleToggle = 'new' | 'resurrecting' | 'returning' | 'dormant'
export type AnyFilterType =
    | TrendsFilterType
    | StickinessFilterType
    | FunnelsFilterType
    | PathsFilterType
    | RetentionFilterType
    | LifecycleFilterType
    | FilterType

export type AnyPartialFilterType =
    | Partial<TrendsFilterType>
    | Partial<StickinessFilterType>
    | Partial<FunnelsFilterType>
    | Partial<PathsFilterType>
    | Partial<RetentionFilterType>
    | Partial<LifecycleFilterType>
    | Partial<FilterType>

export interface EventsListQueryParams {
    event?: string
    properties?: AnyPropertyFilter[] | PropertyGroupFilter
    orderBy?: string[]
    action_id?: number
    after?: string
    before?: string
    limit?: number
    offset?: number
}

export interface RecordingEventsFilters {
    query: string
}

export interface RecordingConsoleLogsFilters {
    query: string
}

export enum RecordingWindowFilter {
    All = 'all',
}

export interface EditorFilterProps {
    query: InsightQueryNode
    insightProps: InsightLogicProps
}

export interface InsightEditorFilter {
    key: string
    label?: string | ((props: EditorFilterProps) => JSX.Element | null)
    tooltip?: JSX.Element
    showOptional?: boolean
    position?: 'left' | 'right'
    valueSelector?: (insight: Partial<InsightModel>) => any
    /** Editor filter component. Cannot be an anonymous function or the key would not work! */
    component?: (props: EditorFilterProps) => JSX.Element | null
}

export type InsightEditorFilterGroup = {
    title?: string
    count?: number
    editorFilters: InsightEditorFilter[]
    defaultExpanded?: boolean
}

export interface SystemStatusSubrows {
    columns: string[]
    rows: string[][]
}

export interface SystemStatusRow {
    metric: string
    value: boolean | string | number | null
    key: string
    description?: string
    subrows?: SystemStatusSubrows
}

export interface SystemStatus {
    overview: SystemStatusRow[]
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

export interface ActionFilter extends EntityFilter {
    math?: string
    math_property?: string
    math_group_type_index?: number | null
    math_hogql?: string
    properties?: AnyPropertyFilter[]
    type: EntityType
}
export interface TrendAPIResponse<ResultType = TrendResult[]> {
    type: 'Trends'
    is_cached: boolean
    last_refresh: string | null
    result: ResultType
    timezone: string
    next: string | null
}

export interface TrendResult {
    action: ActionFilter
    actions?: ActionFilter[]
    count: number
    data: number[]
    days: string[]
    dates?: string[]
    label: string
    labels: string[]
    breakdown_value?: string | number
    aggregated_value: number
    status?: string
    compare_label?: CompareLabelType
    compare?: boolean
    persons_urls?: { url: string }[]
    persons?: Person
    filter?: TrendsFilterType
}

interface Person {
    url: string
    filter: Partial<FilterType>
}

export interface FunnelStep {
    // The type returned from the API.
    action_id: string
    average_conversion_time: number | null
    median_conversion_time: number | null
    count: number
    name: string
    custom_name?: string | null
    order: number
    people?: string[]
    type: EntityType
    labels?: string[]
    breakdown?: BreakdownKeyType
    breakdowns?: BreakdownKeyType[]
    breakdown_value?: BreakdownKeyType
    data?: number[]
    days?: string[]

    /** Url that you can GET to retrieve the people that converted in this step */
    converted_people_url: string

    /** Url that you can GET to retrieve the people that dropped in this step  */
    dropped_people_url: string | null
}

export interface FunnelsTimeConversionBins {
    bins: [number, number][]
    average_conversion_time: number | null
}

export type FunnelResultType = FunnelStep[] | FunnelStep[][] | FunnelsTimeConversionBins

export interface FunnelAPIResponse<ResultType = FunnelResultType> {
    is_cached: boolean
    last_refresh: string | null
    result: ResultType
    timezone: string
}

export interface FunnelStepWithNestedBreakdown extends FunnelStep {
    nested_breakdown?: FunnelStep[]
}

export interface FunnelTimeConversionMetrics {
    averageTime: number
    stepRate: number
    totalRate: number
}

export interface FunnelConversionWindow {
    funnel_window_interval_unit: FunnelConversionWindowTimeUnit
    funnel_window_interval: number
}

// https://github.com/PostHog/posthog/blob/master/posthog/models/filters/mixins/funnel.py#L100
export enum FunnelConversionWindowTimeUnit {
    Second = 'second',
    Minute = 'minute',
    Hour = 'hour',
    Day = 'day',
    Week = 'week',
    Month = 'month',
}

export enum FunnelStepReference {
    total = 'total',
    previous = 'previous',
}

export interface FunnelStepWithConversionMetrics extends FunnelStep {
    droppedOffFromPrevious: number
    conversionRates: {
        fromPrevious: number
        total: number
        fromBasisStep: number // either fromPrevious or total, depending on FunnelStepReference
    }
    nested_breakdown?: Omit<FunnelStepWithConversionMetrics, 'nested_breakdown'>[]
    rowKey?: number | string
    significant?: {
        fromPrevious: boolean
        total: boolean
        fromBasisStep: boolean // either fromPrevious or total, depending on FunnelStepReference
    }
}

export interface FlattenedFunnelStepByBreakdown {
    rowKey: number | string
    isBaseline?: boolean
    breakdown?: BreakdownKeyType
    // :KLUDGE: Data transforms done in `getBreakdownStepValues`
    breakdown_value?: Array<string | number>
    breakdownIndex?: number
    conversionRates?: {
        total: number
    }
    steps?: FunnelStepWithConversionMetrics[]
    significant?: boolean
}

export interface FunnelCorrelation {
    event: Pick<EventType, 'elements' | 'event' | 'properties'>
    odds_ratio: number
    success_count: number
    success_people_url: string
    failure_count: number
    failure_people_url: string
    correlation_type: FunnelCorrelationType.Failure | FunnelCorrelationType.Success
    result_type:
        | FunnelCorrelationResultsType.Events
        | FunnelCorrelationResultsType.Properties
        | FunnelCorrelationResultsType.EventWithProperties
}

export enum FunnelCorrelationType {
    Success = 'success',
    Failure = 'failure',
}

export enum FunnelCorrelationResultsType {
    Events = 'events',
    Properties = 'properties',
    EventWithProperties = 'event_with_properties',
}

export enum BreakdownAttributionType {
    FirstTouch = 'first_touch',
    LastTouch = 'last_touch',
    AllSteps = 'all_events',
    Step = 'step',
}

export interface ChartParams {
    inCardView?: boolean
    inSharedMode?: boolean
    showPersonsModal?: boolean
    /** allows overriding by queries, e.g. setting empty state text*/
    context?: QueryContext
}

export interface HistogramGraphDatum {
    id: number
    bin0: number
    bin1: number
    count: number
    label: string
}

// Shared between insightLogic, dashboardItemLogic, trendsLogic, funnelLogic, pathsLogic, retentionLogic
export interface InsightLogicProps {
    /** currently persisted insight */
    dashboardItemId?: InsightShortId | 'new' | `new-${string}` | null
    /** id of the dashboard the insight is on (when the insight is being displayed on a dashboard) **/
    dashboardId?: DashboardType['id']
    /** cached insight */
    cachedInsight?: Partial<InsightModel> | null
    /** enable this to avoid API requests */
    doNotLoad?: boolean
    /** query when used as ad-hoc insight */
    query?: InsightVizNode
    setQuery?: (node: InsightVizNode) => void
}

export interface SetInsightOptions {
    /** this overrides the in-flight filters on the page, which may not equal the last returned API response */
    overrideFilter?: boolean
    /** calling with this updates the "last saved" filters */
    fromPersistentApi?: boolean
}

export interface Survey {
    /** UUID */
    id: string
    name: string
    type: SurveyType
    description: string
    linked_flag_id: number | null
    linked_flag: FeatureFlagBasicType | null
    targeting_flag: FeatureFlagBasicType | null
    targeting_flag_filters: Pick<FeatureFlagFilters, 'groups'> | undefined
    conditions: { url: string; selector: string; is_headless?: boolean; seenSurveyWaitPeriodInDays?: number } | null
    appearance: SurveyAppearance
    questions: (BasicSurveyQuestion | LinkSurveyQuestion | RatingSurveyQuestion | MultipleSurveyQuestion)[]
    created_at: string
    created_by: UserBasicType | null
    start_date: string | null
    end_date: string | null
    archived: boolean
    remove_targeting_flag?: boolean
}

export enum SurveyType {
    Popover = 'popover',
    Button = 'button',
    FullScreen = 'full_screen',
    Email = 'email',
    API = 'api',
}

export interface SurveyAppearance {
    backgroundColor?: string
    submitButtonColor?: string
    textColor?: string
    submitButtonText?: string
    descriptionTextColor?: string
    ratingButtonColor?: string
    ratingButtonHoverColor?: string
    whiteLabel?: boolean
    displayThankYouMessage?: boolean
    thankYouMessageHeader?: string
    thankYouMessageDescription?: string
}

export interface SurveyQuestionBase {
    question: string
    description?: string | null
    required?: boolean
}

export interface BasicSurveyQuestion extends SurveyQuestionBase {
    type: SurveyQuestionType.Open
}

export interface LinkSurveyQuestion extends SurveyQuestionBase {
    type: SurveyQuestionType.Link
    link: string | null
}

export interface RatingSurveyQuestion extends SurveyQuestionBase {
    type: SurveyQuestionType.Rating
    display: 'number' | 'emoji'
    scale: number
    lowerBoundLabel: string
    upperBoundLabel: string
}

export interface MultipleSurveyQuestion extends SurveyQuestionBase {
    type: SurveyQuestionType.SingleChoice | SurveyQuestionType.MultipleChoice
    choices: string[]
}

export type SurveyQuestion = BasicSurveyQuestion | LinkSurveyQuestion | RatingSurveyQuestion | MultipleSurveyQuestion

export enum SurveyQuestionType {
    Open = 'open',
    MultipleChoice = 'multiple_choice',
    SingleChoice = 'single_choice',
    Rating = 'rating',
    Link = 'link',
}

export interface FeatureFlagGroupType {
    properties?: AnyPropertyFilter[]
    rollout_percentage: number | null
    variant: string | null
    users_affected?: number
}

export interface MultivariateFlagVariant {
    key: string
    name?: string | null
    rollout_percentage: number
}

export interface MultivariateFlagOptions {
    variants: MultivariateFlagVariant[]
}

export interface FeatureFlagFilters {
    groups: FeatureFlagGroupType[]
    multivariate: MultivariateFlagOptions | null
    aggregation_group_type_index?: number | null
    payloads: Record<string, JsonType>
    super_groups?: FeatureFlagGroupType[]
}

export interface FeatureFlagBasicType {
    id: number
    team_id: TeamType['id']
    key: string
    /* The description field (the name is a misnomer because of its legacy). */
    name: string
    filters: FeatureFlagFilters
    deleted: boolean
    active: boolean
    ensure_experience_continuity: boolean | null
}

export interface FeatureFlagType extends Omit<FeatureFlagBasicType, 'id' | 'team_id'> {
    /** Null means that the flag has never been saved yet (it's new). */
    id: number | null
    created_by: UserBasicType | null
    created_at: string | null
    is_simple_flag: boolean
    rollout_percentage: number | null
    experiment_set: string[] | null
    features: EarlyAccessFeatureType[] | null
    surveys: Survey[] | null
    rollback_conditions: FeatureFlagRollbackConditions[]
    performed_rollback: boolean
    can_edit: boolean
    tags: string[]
    usage_dashboard?: number
    analytics_dashboards?: number[] | null
    has_enriched_analytics?: boolean
}

export interface FeatureFlagRollbackConditions {
    threshold: number
    threshold_type: string
    threshold_metric?: FilterType
    operator?: string
}

export interface CombinedFeatureFlagAndValueType {
    feature_flag: FeatureFlagType
    value: boolean | string
}

export enum EarlyAccessFeatureStage {
    Draft = 'draft',
    Concept = 'concept',
    Alpha = 'alpha',
    Beta = 'beta',
    GeneralAvailability = 'general-availability',
    Archived = 'archived',
}

export enum EarlyAccessFeatureTabs {
    OptedIn = 'opted-in',
    OptedOut = 'opted-out',
}

export interface EarlyAccessFeatureType {
    /** UUID */
    id: string
    feature_flag: FeatureFlagBasicType
    name: string
    description: string
    stage: EarlyAccessFeatureStage
    /** Documentation URL. Can be empty. */
    documentation_url: string
    created_at: string
}

export interface NewEarlyAccessFeatureType extends Omit<EarlyAccessFeatureType, 'id' | 'created_at' | 'feature_flag'> {
    feature_flag_id: number | undefined
}

export interface UserBlastRadiusType {
    users_affected: number
    total_users: number
}

export interface PrevalidatedInvite {
    id: string
    target_email: string
    first_name: string
    organization_name: string
}

interface InstancePreferencesInterface {
    /** Whether debug queries option should be shown on the command palette. */
    debug_queries: boolean
    /** Whether paid features showcasing / upsells are completely disabled throughout the app. */
    disable_paid_fs: boolean
}

export interface PreflightStatus {
    // Attributes that accept undefined values (i.e. `?`) are not received when unauthenticated
    django: boolean
    plugins: boolean
    redis: boolean
    db: boolean
    clickhouse: boolean
    kafka: boolean
    /** An initiated instance is one that already has any organization(s). */
    initiated: boolean
    /** Org creation is allowed on Cloud OR initiated self-hosted organizations with a license and MULTI_ORG_ENABLED. */
    can_create_org: boolean
    /** Whether this is PostHog Cloud. */
    cloud: boolean
    /** Whether this is a managed demo environment. */
    demo: boolean
    celery: boolean
    realm: Realm
    region: Region
    available_social_auth_providers: AuthBackends
    available_timezones?: Record<string, number>
    opt_out_capture?: boolean
    email_service_available: boolean
    slack_service: {
        available: boolean
        client_id?: string
    }
    /** Whether PostHog is running in DEBUG mode. */
    is_debug?: boolean
    licensed_users_available?: number | null
    openai_available?: boolean
    site_url?: string
    instance_preferences?: InstancePreferencesInterface
    buffer_conversion_seconds?: number
    object_storage: boolean
}

export enum ItemMode { // todo: consolidate this and dashboardmode
    Edit = 'edit',
    View = 'view',
    Subscriptions = 'subscriptions',
    Sharing = 'sharing',
}

export enum DashboardPlacement {
    Dashboard = 'dashboard', // When on the standard dashboard page
    ProjectHomepage = 'project-homepage', // When embedded on the project homepage
    FeatureFlag = 'feature-flag',
    Public = 'public', // When viewing the dashboard publicly
    Export = 'export', // When the dashboard is being exported (alike to being printed)
    Person = 'person', // When the dashboard is being viewed on a person page
    Group = 'group', // When the dashboard is being viewed on a group page
}

export enum DashboardMode { // Default mode is null
    Edit = 'edit', // When the dashboard is being edited
    Fullscreen = 'fullscreen', // When the dashboard is on full screen (presentation) mode
    Sharing = 'sharing', // When the sharing configuration is opened
}

// Hotkeys for local (component) actions
export type HotKey =
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
    | 'enter'
    | 'space'
    | 'tab'
    | 'arrowleft'
    | 'arrowright'
    | 'arrowdown'
    | 'arrowup'
    | 'forwardslash'

export type HotKeyOrModifier = HotKey | 'shift' | 'option' | 'command'

export interface EventDefinition {
    id: string
    name: string
    description?: string
    tags?: string[]
    owner?: UserBasicType | null
    created_at?: string
    last_seen_at?: string
    last_updated_at?: string // alias for last_seen_at to achieve event and action parity
    updated_at?: string
    updated_by?: UserBasicType | null
    verified?: boolean
    verified_at?: string
    verified_by?: string
    is_action?: boolean
}

// TODO duplicated from plugin server. Follow-up to de-duplicate
export enum PropertyType {
    DateTime = 'DateTime',
    String = 'String',
    Numeric = 'Numeric',
    Boolean = 'Boolean',
    Duration = 'Duration',
    Selector = 'Selector',
}

export enum PropertyDefinitionType {
    Event = 'event',
    Person = 'person',
    Group = 'group',
}

export interface PropertyDefinition {
    id: string
    name: string
    description?: string
    tags?: string[]
    updated_at?: string
    updated_by?: UserBasicType | null
    is_numerical?: boolean // Marked as optional to allow merge of EventDefinition & PropertyDefinition
    is_seen_on_filtered_events?: boolean // Indicates whether this property has been seen for a particular set of events (when `eventNames` query string is sent); calculated at query time, not stored in the db
    property_type?: PropertyType
    type?: PropertyDefinitionType
    created_at?: string // TODO: Implement
    last_seen_at?: string // TODO: Implement
    example?: string
    is_action?: boolean
    verified?: boolean
    verified_at?: string
    verified_by?: string
}

export enum PropertyDefinitionState {
    Pending = 'pending',
    Loading = 'loading',
    Missing = 'missing',
    Error = 'error',
}

export type Definition = EventDefinition | PropertyDefinition

export interface PersonProperty {
    id: number
    name: string
    count: number
}

export interface GroupType {
    group_type: string
    group_type_index: number
    name_singular?: string | null
    name_plural?: string | null
}

export type GroupTypeProperties = Record<number, Array<PersonProperty>>

export interface Group {
    group_type_index: number
    group_key: string
    created_at: string
    group_properties: Record<string, any>
}

export interface Experiment {
    id: number | 'new'
    name: string
    description?: string
    feature_flag_key: string
    feature_flag?: FeatureFlagBasicType
    filters: FilterType
    parameters: {
        minimum_detectable_effect?: number
        recommended_running_time?: number
        recommended_sample_size?: number
        feature_flag_variants: MultivariateFlagVariant[]
        custom_exposure_filter?: FilterType
        aggregation_group_type_index?: number
    }
    start_date?: string | null
    end_date?: string | null
    archived?: boolean
    secondary_metrics: SecondaryExperimentMetric[]
    created_at: string | null
    created_by: UserBasicType | null
    updated_at: string | null
}

export interface FunnelExperimentVariant {
    key: string
    success_count: number
    failure_count: number
}

export interface TrendExperimentVariant {
    key: string
    count: number
    exposure: number
    absolute_exposure: number
}

interface BaseExperimentResults {
    probability: Record<string, number>
    fakeInsightId: string
    significant: boolean
    noData?: boolean
    significance_code: SignificanceCode
    expected_loss?: number
    p_value?: number
}

export interface _TrendsExperimentResults extends BaseExperimentResults {
    insight: TrendResult[]
    filters: TrendsFilterType
    variants: TrendExperimentVariant[]
    last_refresh?: string | null
}

export interface _FunnelExperimentResults extends BaseExperimentResults {
    insight: FunnelStep[][]
    filters: FunnelsFilterType
    variants: FunnelExperimentVariant[]
    last_refresh?: string | null
}

export interface TrendsExperimentResults {
    result: _TrendsExperimentResults
    is_cached?: boolean
    last_refresh?: string | null
}
export interface FunnelExperimentResults {
    result: _FunnelExperimentResults
    is_cached?: boolean
    last_refresh?: string | null
}

export type ExperimentResults = TrendsExperimentResults | FunnelExperimentResults

export interface SecondaryExperimentMetric {
    name: string
    filters: Partial<FilterType>
}

export interface SelectOption {
    value: string
    label?: string
}

export enum FilterLogicalOperator {
    And = 'AND',
    Or = 'OR',
}

export interface PropertyGroupFilter {
    type: FilterLogicalOperator
    values: PropertyGroupFilterValue[]
}

export interface PropertyGroupFilterValue {
    type: FilterLogicalOperator
    values: (AnyPropertyFilter | PropertyGroupFilterValue)[]
}

export interface CohortCriteriaGroupFilter {
    id?: string
    type: FilterLogicalOperator
    values: AnyCohortCriteriaType[] | CohortCriteriaGroupFilter[]
}

export interface SelectOptionWithChildren extends SelectOption {
    children: React.ReactChildren
    ['data-attr']: string
    key: string
}

export interface KeyMapping {
    label: string
    description?: string | JSX.Element
    examples?: (string | number)[]
    /** System properties are hidden in properties table by default. */
    system?: boolean
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
    current_team: TeamType | TeamPublicType | null
    preflight: PreflightStatus
    default_event_name: string
    persisted_feature_flags?: string[]
    anonymous: boolean
    frontend_apps?: Record<number, FrontendAppConfig>
    /** Whether the user was autoswitched to the current item's team. */
    switched_team: TeamType['id'] | null
}

export type StoredMetricMathOperations = 'max' | 'min' | 'sum'

export interface PathEdgeParameters {
    edge_limit?: number | undefined
    min_edge_weight?: number | undefined
    max_edge_weight?: number | undefined
}

export enum SignificanceCode {
    Significant = 'significant',
    NotEnoughExposure = 'not_enough_exposure',
    LowWinProbability = 'low_win_probability',
    HighLoss = 'high_loss',
    HighPValue = 'high_p_value',
}

export enum HelpType {
    Slack = 'slack',
    GitHub = 'github',
    Email = 'email',
    Docs = 'docs',
    Updates = 'updates',
    SupportForm = 'support_form',
}

export interface DateMappingOption {
    key: string
    inactive?: boolean // Options removed due to low usage (see relevant PR); will not show up for new insights but will be kept for existing
    values: string[]
    getFormattedDate?: (date: dayjs.Dayjs, format?: string) => string
    defaultInterval?: IntervalType
}

export interface Breadcrumb {
    /** Name to display. */
    name: string | null | undefined
    /** Symbol, e.g. a lettermark or a profile picture. */
    symbol?: React.ReactNode
    /** Path to link to. */
    path?: string
    /** Whether to show a custom popover */
    popover?: Pick<PopoverProps, 'overlay' | 'sameWidth' | 'actionable'>
}

export enum GraphType {
    Bar = 'bar',
    HorizontalBar = 'horizontalBar',
    Line = 'line',
    Histogram = 'histogram',
    Pie = 'doughnut',
}

export type GraphDataset = ChartDataset<ChartType> &
    Partial<
        Pick<
            TrendResult,
            | 'count'
            | 'label'
            | 'days'
            | 'labels'
            | 'data'
            | 'compare'
            | 'compare_label'
            | 'status'
            | 'action'
            | 'actions'
            | 'breakdown_value'
            | 'persons_urls'
            | 'persons'
            | 'filter'
        >
    > & {
        /** Used in filtering out visibility of datasets. Set internally by chart.js */
        id: number
        /** Toggled on to draw incompleteness lines in LineGraph.tsx */
        dotted?: boolean
        /** Array of breakdown values used only in ActionsHorizontalBar.tsx data */
        breakdownValues?: (string | number | undefined)[]
        /** Array of compare labels used only in ActionsHorizontalBar.tsx data */
        compareLabels?: (CompareLabelType | undefined)[]
        /** Array of persons ussed only in (ActionsHorizontalBar|ActionsPie).tsx */
        personsValues?: (Person | undefined)[]
        index?: number
        /** Value (count) for specific data point; only valid in the context of an xy intercept */
        pointValue?: number
        /** Value (count) for specific data point; only valid in the context of an xy intercept */
        personUrl?: string
        /** Action/event filter defition */
        action?: ActionFilter
    }

export type GraphPoint = InteractionItem & { dataset: GraphDataset }

interface PointsPayload {
    pointsIntersectingLine: GraphPoint[]
    pointsIntersectingClick: GraphPoint[]
    clickedPointNotLine: boolean
    referencePoint: GraphPoint
}

export interface GraphPointPayload {
    points: PointsPayload
    index: number
    value?: number
    /** Contains the dataset for all the points in the same x-axis point; allows switching between matching points in the x-axis */
    crossDataset?: GraphDataset[]
    /** ID for the currently selected series */
    seriesId?: number
}

export enum CompareLabelType {
    Current = 'current',
    Previous = 'previous',
}

export interface InstanceSetting {
    key: string
    value: boolean | string | number | null
    value_type: 'bool' | 'str' | 'int'
    description?: string
    editable: boolean
    is_secret: boolean
}

export enum BaseMathType {
    TotalCount = 'total',
    UniqueUsers = 'dau',
    WeeklyActiveUsers = 'weekly_active',
    MonthlyActiveUsers = 'monthly_active',
    UniqueSessions = 'unique_session',
}

export enum PropertyMathType {
    Average = 'avg',
    Sum = 'sum',
    Minimum = 'min',
    Maximum = 'max',
    Median = 'median',
    P90 = 'p90',
    P95 = 'p95',
    P99 = 'p99',
}

export enum CountPerActorMathType {
    Average = 'avg_count_per_actor',
    Minimum = 'min_count_per_actor',
    Maximum = 'max_count_per_actor',
    Median = 'median_count_per_actor',
    P90 = 'p90_count_per_actor',
    P95 = 'p95_count_per_actor',
    P99 = 'p99_count_per_actor',
}

export enum HogQLMathType {
    HogQL = 'hogql',
}
export enum GroupMathType {
    UniqueGroup = 'unique_group',
}

export enum ActorGroupType {
    Person = 'person',
    GroupPrefix = 'group',
}

export enum BehavioralEventType {
    PerformEvent = 'performed_event',
    PerformMultipleEvents = 'performed_event_multiple',
    PerformSequenceEvents = 'performed_event_sequence',
    NotPerformedEvent = 'not_performed_event',
    NotPerformSequenceEvents = 'not_performed_event_sequence',
    HaveProperty = 'have_property',
    NotHaveProperty = 'not_have_property',
}

export enum BehavioralCohortType {
    InCohort = 'in_cohort',
    NotInCohort = 'not_in_cohort',
}

export enum BehavioralLifecycleType {
    PerformEventFirstTime = 'performed_event_first_time',
    PerformEventRegularly = 'performed_event_regularly',
    StopPerformEvent = 'stopped_performing_event',
    StartPerformEventAgain = 'restarted_performing_event',
}

export enum TimeUnitType {
    Day = 'day',
    Week = 'week',
    Month = 'month',
    Year = 'year',
}

export enum DateOperatorType {
    BeforeTheLast = 'before_the_last',
    Between = 'between',
    NotBetween = 'not_between',
    OnTheDate = 'on_the_date',
    NotOnTheDate = 'not_on_the_date',
    Since = 'since',
    Before = 'before',
    IsSet = 'is_set',
    IsNotSet = 'is_not_set',
}

export enum ValueOptionType {
    MostRecent = 'most_recent',
    Previous = 'previous',
    OnDate = 'on_date',
}

export type WeekdayType = 'monday' | 'tuesday' | 'wednesday' | 'thursday' | 'friday' | 'saturday' | 'sunday'

export interface SubscriptionType {
    id: number
    insight?: number
    dashboard?: number
    target_type: string
    target_value: string
    frequency: 'daily' | 'weekly' | 'monthly' | 'yearly'
    interval: number
    byweekday: WeekdayType[] | null
    bysetpos: number | null
    start_date: string
    until_date?: string
    title: string
    summary: string
    created_by?: UserBasicType | null
    created_at: string
    updated_at: string
    deleted?: boolean
}

export type SmallTimeUnit = 'hours' | 'minutes' | 'seconds'

export type Duration = {
    timeValue: number
    unit: SmallTimeUnit
}

export enum EventDefinitionType {
    Event = 'event',
    EventCustom = 'event_custom',
    EventPostHog = 'event_posthog',
}

export interface IntegrationType {
    id: number
    kind: 'slack'
    config: any
    created_by?: UserBasicType | null
    created_at: string
}

export interface SlackChannelType {
    id: string
    name: string
    is_private: boolean
    is_ext_shared: boolean
    is_member: boolean
}

export interface SharingConfigurationType {
    enabled: boolean
    access_token: string
    created_at: string
}

export enum ExporterFormat {
    PNG = 'image/png',
    CSV = 'text/csv',
    PDF = 'application/pdf',
    JSON = 'application/json',
}

/** Exporting directly from the browser to a file */
export type LocalExportContext = {
    localData: string
    filename: string
    mediaType: ExporterFormat
}

export type OnlineExportContext = {
    method?: string
    path: string
    query?: any
    body?: any
    filename?: string
    max_limit?: number
}

export type QueryExportContext = {
    source: Record<string, any>
    filename?: string
    max_limit?: number
}

export type ExportContext = OnlineExportContext | LocalExportContext | QueryExportContext

export interface ExportedAssetType {
    id: number
    export_format: ExporterFormat
    dashboard?: number
    insight?: number
    export_context?: ExportContext
    has_content: boolean
    filename: string
    expires_after?: Dayjs
}

export enum FeatureFlagReleaseType {
    ReleaseToggle = 'Release toggle',
    Variants = 'Multiple variants',
}

export interface MediaUploadResponse {
    id: string
    image_location: string
    name: string
}

export enum RolloutConditionType {
    Insight = 'insight',
    Sentry = 'sentry',
}

export enum Resource {
    FEATURE_FLAGS = 'feature flags',
}

export enum AccessLevel {
    READ = 21,
    WRITE = 37,
}

export interface RoleType {
    id: string
    name: string
    feature_flags_access_level: AccessLevel
    members: RoleMemberType[]
    associated_flags: { id: number; key: string }[]
    created_at: string
    created_by: UserBasicType | null
}

export interface RolesListParams {
    feature_flags_access_level?: AccessLevel
}

export interface FeatureFlagAssociatedRoleType {
    id: string
    feature_flag: FeatureFlagType | null
    role: RoleType
    updated_at: string
    added_at: string
}

export interface RoleMemberType {
    id: string
    user: UserBaseType
    role_id: string
    joined_at: string
    updated_at: string
    user_uuid: string
}

export interface OrganizationResourcePermissionType {
    id: string
    resource: Resource
    access_level: AccessLevel
    created_at: string
    updated_at: string
    created_by: UserBaseType | null
}

export interface RecordingReportLoadTimeRow {
    size?: number
    duration: number
}

export interface RecordingReportLoadTimes {
    metadata: RecordingReportLoadTimeRow
    snapshots: RecordingReportLoadTimeRow
    events: RecordingReportLoadTimeRow
    firstPaint: RecordingReportLoadTimeRow
}

export type JsonType = string | number | boolean | null | { [key: string]: JsonType } | Array<JsonType>

export type PromptButtonType = 'primary' | 'secondary'
export type PromptType = 'modal' | 'popup'

export type PromptPayload = {
    title: string
    body: string
    type: PromptType
    image?: string
    url_match?: string
    primaryButtonText?: string
    secondaryButtonText?: string
    primaryButtonURL?: string
}

export type PromptFlag = {
    flag: string
    payload: PromptPayload
    showingPrompt: boolean
    locationCSS?: Partial<CSSStyleDeclaration>
    tooltipCSS?: Partial<CSSStyleDeclaration>
}

export type NotebookListItemType = {
    // id: string
    short_id: string
    title?: string
    is_template?: boolean
    created_at: string
    created_by: UserBasicType | null
    last_modified_at?: string
    last_modified_by?: UserBasicType | null
}

export type NotebookType = NotebookListItemType & {
    content: JSONContent // TODO: Type this better
    version: number
    // used to power text-based search
    text_content?: string | null
}

export enum NotebookNodeType {
    Insight = 'ph-insight',
    Query = 'ph-query',
    Recording = 'ph-recording',
    RecordingPlaylist = 'ph-recording-playlist',
    FeatureFlag = 'ph-feature-flag',
    FeatureFlagCodeExample = 'ph-feature-flag-code-example',
    Experiment = 'ph-experiment',
    EarlyAccessFeature = 'ph-early-access-feature',
    Survey = 'ph-survey',
    Person = 'ph-person',
    Backlink = 'ph-backlink',
    ReplayTimestamp = 'ph-replay-timestamp',
    Image = 'ph-image',
}

export type NotebookNodeResource = {
    attrs: Record<string, any>
    type: NotebookNodeType
}

export enum NotebookTarget {
    Popover = 'popover',
    Auto = 'auto',
}

export type NotebookSyncStatus = 'synced' | 'saving' | 'unsaved' | 'local'

export type NotebookPopoverVisibility = 'hidden' | 'visible' | 'peek'

export interface DataWarehouseCredential {
    access_key: string
    access_secret: string
}
export interface DataWarehouseTable {
    /** UUID */
    id: string
    name: string
    format: string
    url_pattern: string
    credential: DataWarehouseCredential
    columns: DatabaseSchemaQueryResponseField[]
}

export type DataWarehouseTableTypes = 'CSV' | 'Parquet'

export interface DataWarehouseSavedQuery {
    /** UUID */
    id: string
    name: string
    query: HogQLQuery
    columns: DatabaseSchemaQueryResponseField[]
}

export interface DataWarehouseViewLink {
    id: string
    saved_query_id?: string
    saved_query?: string
    table?: string
    to_join_key?: string
    from_join_key?: string
}

export type BatchExportDestinationS3 = {
    type: 'S3'
    config: {
        bucket_name: string
        region: string
        prefix: string
        aws_access_key_id: string
        aws_secret_access_key: string
        exclude_events: string[]
        compression: string | null
        encryption: string | null
        kms_key_id: string | null
    }
}

export type BatchExportDestinationPostgres = {
    type: 'Postgres'
    config: {
        user: string
        password: string
        host: string
        port: number
        database: string
        schema: string
        table_name: string
        has_self_signed_cert: boolean
    }
}

export type BatchExportDestinationSnowflake = {
    type: 'Snowflake'
    config: {
        account: string
        database: string
        warehouse: string
        user: string
        password: string
        schema: string
        table_name: string
        role: string | null
    }
}

export type BatchExportDestinationBigQuery = {
    type: 'BigQuery'
    config: {
        project_id: string
        private_key: string
        private_key_id: string
        client_email: string
        token_uri: string
        dataset_id: string
        table_id: string
        exclude_events: string[]
    }
}

export type BatchExportDestination =
    | BatchExportDestinationS3
    | BatchExportDestinationSnowflake
    | BatchExportDestinationPostgres
    | BatchExportDestinationBigQuery

export type BatchExportConfiguration = {
    // User provided data for the export. This is the data that the user
    // provides when creating the export.
    id: string
    name: string
    destination: BatchExportDestination
    interval: 'hour' | 'day'
    created_at: string
    start_at: string | null
    end_at: string | null
    paused: boolean
    latest_runs?: BatchExportRun[]
}

export type BatchExportRun = {
    id: string
    status: 'Cancelled' | 'Completed' | 'ContinuedAsNew' | 'Failed' | 'Terminated' | 'TimedOut' | 'Running' | 'Starting'
    created_at: Dayjs
    data_interval_start: Dayjs
    data_interval_end: Dayjs
    last_updated_at?: Dayjs
}

export type GroupedBatchExportRuns = {
    last_run_at: Dayjs
    data_interval_start: Dayjs
    data_interval_end: Dayjs
    runs: BatchExportRun[]
}

export type SDK = {
    name: string
    key: string
    recommended?: boolean
    tags: string[]
    image: string | JSX.Element
    docsLink: string
}

export enum SDKKey {
    JS_WEB = 'javascript_web',
    REACT = 'react',
    NEXT_JS = 'nextjs',
    GATSBY = 'gatsby',
    IOS = 'ios',
    ANDROID = 'android',
    FLUTTER = 'flutter',
    REACT_NATIVE = 'react_native',
    NODE_JS = 'nodejs',
    RUBY = 'ruby',
    PYTHON = 'python',
    PHP = 'php',
    GO = 'go',
    ELIXIR = 'elixir',
    API = 'api',
    JAVA = 'java',
    RUST = 'rust',
    GOOGLE_TAG_MANAGER = 'google_tag_manager',
    NUXT_JS = 'nuxtjs',
    VUE_JS = 'vuejs',
    SEGMENT = 'segment',
    RUDDERSTACK = 'rudderstack',
    DOCUSAURUS = 'docusaurus',
    SHOPIFY = 'shopify',
    WORDPRESS = 'wordpress',
    SENTRY = 'sentry',
    RETOOL = 'retool',
}

export enum SDKTag {
    WEB = 'Web',
    MOBILE = 'Mobile',
    SERVER = 'Server',
    INTEGRATION = 'Integration',
    RECOMMENDED = 'Recommended',
    OTHER = 'Other',
}

export type SDKInstructionsMap = Partial<Record<SDKKey, React.ReactNode>>
