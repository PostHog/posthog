import {
    OrganizationMembershipLevel,
    PluginsAccessLevel,
    ShownAsValue,
    RETENTION_RECURRING,
    RETENTION_FIRST_TIME,
    ENTITY_MATCH_TYPE,
    FunnelLayout,
    BIN_COUNT_AUTO,
    TeamMembershipLevel,
} from 'lib/constants'
import { PluginConfigSchema } from '@posthog/plugin-scaffold'
import { PluginInstallationType } from 'scenes/plugins/types'
import { PROPERTY_MATCH_TYPE, DashboardRestrictionLevel, DashboardPrivilegeLevel } from 'lib/constants'
import { UploadFile } from 'antd/lib/upload/interface'
import { eventWithTime } from 'rrweb/typings/types'
import { PostHog } from 'posthog-js'
import { Dayjs, dayjs } from 'lib/dayjs'
import { ChartDataset, ChartType, InteractionItem } from 'chart.js'
import { LogLevel } from 'rrweb'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { BehavioralFilterKey, BehavioralFilterType } from 'scenes/cohorts/CohortFilters/types'
import { LogicWrapper } from 'kea'
import { AggregationAxisFormat } from 'scenes/insights/aggregationAxisFormat'
import { RowStatus } from 'scenes/session-recordings/player/list/listLogic'
import { Layout } from 'react-grid-layout'

export type Optional<T, K extends string | number | symbol> = Omit<T, K> & { [K in keyof T]?: T[K] }

// Keep this in sync with backend constants (constants.py)
export enum AvailableFeature {
    ZAPIER = 'zapier',
    ORGANIZATIONS_PROJECTS = 'organizations_projects',
    PROJECT_BASED_PERMISSIONING = 'project_based_permissioning',
    GOOGLE_LOGIN = 'google_login',
    SAML = 'saml',
    SSO_ENFORCEMENT = 'sso_enforcement',
    DASHBOARD_COLLABORATION = 'dashboard_collaboration',
    DASHBOARD_PERMISSIONING = 'dashboard_permissioning',
    INGESTION_TAXONOMY = 'ingestion_taxonomy',
    PATHS_ADVANCED = 'paths_advanced',
    CORRELATION_ANALYSIS = 'correlation_analysis',
    GROUP_ANALYTICS = 'group_analytics',
    MULTIVARIATE_FLAGS = 'multivariate_flags',
    EXPERIMENTATION = 'experimentation',
    TAGGING = 'tagging',
    BEHAVIORAL_COHORT_FILTERING = 'behavioral_cohort_filtering',
    WHITE_LABELLING = 'white_labelling',
    SUBSCRIPTIONS = 'subscriptions',
    APP_METRICS = 'app_metrics',
    RECORDINGS_PLAYLISTS = 'recordings_playlists',
    ROLE_BASED_ACCESS = 'role_based_access',
    RECORDINGS_FILE_EXPORT = 'recordings_file_export',
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

export type SSOProviders = 'google-oauth2' | 'github' | 'gitlab' | 'saml'

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
    id: number
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
    posthog_version?: string
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
    taxonomy_set_events_count: number
    taxonomy_set_properties_count: number
}

export interface OrganizationType extends OrganizationBasicType {
    created_at: string
    updated_at: string
    plugins_access_level: PluginsAccessLevel
    teams: TeamBasicType[] | null
    available_features: AvailableFeature[]
    is_member_join_email_enabled: boolean
    customer_id: string | null
    metadata?: OrganizationMetadata
}

export interface OrganizationDomainType {
    id: string
    domain: string
    is_verified: boolean
    verified_at: string // Datetime
    verification_challenge: string
    jit_provisioning_enabled: boolean
    sso_enforcement: SSOProviders | ''
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
}

export interface OrganizationMemberType extends BaseMemberType {
    /** Level at which the user is in the organization. */
    level: OrganizationMembershipLevel
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
    ingested_event: boolean
    is_demo: boolean
    timezone: string
    /** Whether the project is private. */
    access_control: boolean
    /** Effective access level of the user in this specific team. Null if user has no access. */
    effective_membership_level: OrganizationMembershipLevel | null
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
    session_recording_opt_in: boolean
    capture_console_log_opt_in: boolean

    capture_performance_opt_in: boolean
    test_account_filters: AnyPropertyFilter[]
    test_account_filters_default_checked: boolean
    path_cleaning_filters: Record<string, any>[]
    data_attributes: string[]
    person_display_name_properties: string[]
    has_group_types: boolean
    primary_dashboard: number // Dashboard shown on the project homepage
    live_events_columns: string[] | null // Custom columns shown on the Live Events page
    /** Used to exclude person properties from correlation analysis results.
     *
     * For example can be used to exclude properties that have trivial causation.
     * This field should have a default value of `{}`, but it IS nullable and can be `null` in some cases.
     */
    correlation_config: CorrelationConfigType | null
    person_on_events_querying_enabled: boolean
    groups_on_events_querying_enabled: boolean
}

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
}

/** Sync with plugin-server/src/types.ts */
export enum ActionStepUrlMatching {
    Contains = 'contains',
    Regex = 'regex',
    Exact = 'exact',
}

export interface ActionStepType {
    event?: string
    href?: string | null
    id?: number
    name?: string
    properties?: AnyPropertyFilter[]
    selector?: string | null
    tag_name?: string
    text?: string | null
    url?: string | null
    url_matching?: ActionStepUrlMatching
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

export enum SessionRecordingsTabs {
    Recent = 'recent',
    Playlists = 'playlists',
    FilePlayback = 'file-playback',
}

export enum ExperimentsTabs {
    All = 'all',
    Yours = 'yours',
    Archived = 'archived',
}

export enum ExperimentStatus {
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
}

/** Sync with plugin-server/src/types.ts */
interface BasePropertyFilter {
    key: string
    value: PropertyFilterValue
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

export type PropertyFilter =
    | EventPropertyFilter
    | PersonPropertyFilter
    | ElementPropertyFilter
    | SessionPropertyFilter
    | CohortPropertyFilter
    | RecordingDurationFilter
    | GroupPropertyFilter
    | FeaturePropertyFilter

export type AnyPropertyFilter =
    | Partial<EventPropertyFilter>
    | Partial<PersonPropertyFilter>
    | Partial<ElementPropertyFilter>
    | Partial<SessionPropertyFilter>
    | Partial<CohortPropertyFilter>
    | Partial<RecordingDurationFilter>
    | Partial<GroupPropertyFilter>
    | Partial<FeaturePropertyFilter>

export type AnyFilterLike = AnyPropertyFilter | PropertyGroupFilter | PropertyGroupFilterValue

export type SessionRecordingId = SessionRecordingType['id']

export interface PlayerPosition {
    time: number
    windowId: string
}

export interface RRWebRecordingConsoleLogPayload {
    level: LogLevel
    payload: (string | null)[]
    trace: string[]
}

export interface RecordingConsoleLog extends RecordingTimeMixinType {
    parsedPayload: string
    hash?: string // md5() on parsedPayload. Used for deduping console logs.
    count?: number // Number of duplicate console logs
    previewContent?: React.ReactNode // Content to show in first line
    fullContent?: React.ReactNode // Full content to show when item is expanded
    traceContent?: React.ReactNode // Url content to show on right side
    rawString: string // Raw text used for fuzzy search
    level: LogLevel
}

export interface RecordingSegment {
    startPlayerPosition: PlayerPosition // Player time (for the specific window_id's player) that the segment starts. If the segment starts 10 seconds into a recording, this would be 10000
    endPlayerPosition: PlayerPosition // Player time (for the specific window_id' player) that the segment ends
    startTimeEpochMs: number // Epoch time that the segment starts
    endTimeEpochMs: number // Epoch time that the segment ends
    durationMs: number
    windowId: string
    isActive: boolean
}

export interface RecordingStartAndEndTime {
    startTimeEpochMs: number
    endTimeEpochMs: number
}

export interface SessionRecordingMeta {
    segments: RecordingSegment[]
    startAndEndTimesByWindowId: Record<string, RecordingStartAndEndTime>
    recordingDurationMs: number
    playlists?: SessionRecordingPlaylistType['id'][]
}

export interface SessionPlayerSnapshotData {
    snapshotsByWindowId: Record<string, eventWithTime[]>
    next?: string
}

export interface SessionPlayerMetaData {
    person: PersonType | null
    metadata: SessionRecordingMeta
}

export interface SessionPlayerData extends SessionPlayerSnapshotData, SessionPlayerMetaData {
    bufferedTo: PlayerPosition | null
}

export enum SessionRecordingUsageType {
    VIEWED = 'viewed',
    ANALYZED = 'analyzed',
    LOADED = 'loaded',
}

export enum SessionRecordingPlayerTab {
    EVENTS = 'events',
    CONSOLE = 'console',
}

export enum SessionPlayerState {
    BUFFER = 'buffer',
    PLAY = 'play',
    PAUSE = 'pause',
    SCRUB = 'scrub',
    SKIP = 'skip',
    ERROR = 'error',
}

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

export interface RecordingFilters {
    date_from?: string | null
    date_to?: string | null
    events?: FilterType['events']
    actions?: FilterType['actions']
    properties?: AnyPropertyFilter[]
    offset?: number
    session_recording_duration?: RecordingDurationFilter
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
    NEW_ENTITY = 'new_entity',
}

export type EntityFilter = {
    type?: EntityType
    id: Entity['id'] | null
    name: string | null
    custom_name?: string
    index?: number
    order?: number
}

export interface FunnelStepRangeEntityFilter {
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
}

export interface MatchedRecordingEvents {
    uuid: string
    session_id: string
    window_id: string
    timestamp: string
}

export interface MatchedRecording {
    session_id?: string
    events: MatchedRecordingEvents[]
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
}

export enum LayoutView {
    Card = 'card',
    List = 'list',
}

export interface EventsTableAction {
    name: string
    id: string
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
    /** Used in session recording events list */
    colonTimestamp?: string
}

export interface RecordingTimeMixinType {
    playerTime: number | null
    playerPosition: PlayerPosition | null
    colonTimestamp?: string
    capturedInWindow?: boolean // Did the event or console log not originate from the same client library as the recording
}

export interface RecordingEventType extends EventType, RecordingTimeMixinType {
    percentageOfRecordingDuration: number // Used to place the event on the seekbar
    level?: RowStatus.Match | RowStatus.Information // If undefined, by default information row
}

export interface EventsTableRowItem {
    event?: EventType
    date_break?: string
    new_events?: boolean
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
    /** List of matching events. **/
    matching_events?: MatchedRecording[]
    distinct_id?: string
    email?: string
    person?: PersonType
    /** List of static playlists that this recording is referenced on */
    playlists?: SessionRecordingPlaylistType['id'][]
    click_count?: number
    keypress_count?: number
    urls?: string[]
}

export interface SessionRecordingPropertiesType {
    id: string
    properties?: Record<string, any>
}

export interface SessionRecordingEvents {
    next?: string
    events: RecordingEventType[]
}

export interface CurrentBillCycleType {
    current_period_start: number
    current_period_end: number
}

export interface BillingType {
    should_setup_billing: boolean
    is_billing_active: boolean
    plan: PlanInterface | null
    billing_period_ends: string | null
    event_allocation: number | null
    current_usage: number | null
    subscription_url: string
    current_bill_amount: number | null
    current_bill_usage: number | null
    should_display_current_bill: boolean
    billing_limit: number | null
    billing_limit_exceeded: boolean | null
    current_bill_cycle: CurrentBillCycleType | null
    tiers: BillingTierType[] | null
}

export type BillingVersion = 'v1' | 'v2'

export interface BillingProductV2Type {
    type: 'EVENTS' | 'RECORDINGS'
    name: string
    description: string
    price_description: string
    image_url?: string
    free_allocation?: number
    tiers: {
        unit_amount_usd: string
        current_amount_usd?: string | null
        up_to: number | null
    }[]
    tiered: boolean
    current_usage?: number
    projected_usage?: number
    percentage_usage: number
    current_amount_usd?: string
    usage_limit?: number
    unit_amount_usd: string | null
}

export interface BillingV2Type {
    customer_id: string
    has_active_subscription: boolean
    free_trial_until?: Dayjs
    stripe_portal_url?: string
    deactivated?: boolean
    current_total_amount_usd?: string
    products: BillingProductV2Type[]
    products_enterprise?: BillingProductV2Type[]

    custom_limits_usd?: {
        [key: string]: string | null | undefined
    }
    billing_period?: {
        current_period_start: Dayjs
        current_period_end: Dayjs
    }
    license?: {
        plan: LicensePlan
    }
}

export interface BillingTierType {
    name: string
    price_per_event: number
    number_of_events: number
    subtotal: number
    running_total: number
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
    filters_hash: string
    refreshing: boolean
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
    dashboards: number[] | null
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
}

export interface DashboardType {
    id: number
    name: string
    description: string
    pinned: boolean
    tiles: DashboardTile[]
    created_at: string
    created_by: UserBasicType | null
    is_shared: boolean
    deleted: boolean
    filters: Record<string, any>
    creation_mode: 'default' | 'template' | 'duplicate'
    restriction_level: DashboardRestrictionLevel
    effective_restriction_level: DashboardRestrictionLevel
    effective_privilege_level: DashboardPrivilegeLevel
    tags?: string[]
    /** Purely local value to determine whether the dashboard should be highlighted, e.g. as a fresh duplicate. */
    _highlight?: boolean
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
    capabilities?: Record<'jobs' | 'methods' | 'scheduled_tasks', string[]>
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
    content: string
    date_marker: string
    created_by?: UserBasicType | null
    created_at: string
    updated_at: string
    dashboard_item?: number | null
    insight_short_id?: InsightModel['short_id'] | null
    insight_name?: InsightModel['name'] | null
    deleted?: boolean
    creation_type?: string
}

export interface AnnotationType extends Omit<RawAnnotationType, 'date_marker'> {
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

export type BreakdownType = 'cohort' | 'person' | 'event' | 'group' | 'session'
export type IntervalType = 'hour' | 'day' | 'week' | 'month'
export type SmoothingType = number

export enum InsightType {
    TRENDS = 'TRENDS',
    STICKINESS = 'STICKINESS',
    LIFECYCLE = 'LIFECYCLE',
    FUNNELS = 'FUNNELS',
    RETENTION = 'RETENTION',
    PATHS = 'PATHS',
}

export enum PathType {
    PageView = '$pageview',
    Screen = '$screen',
    CustomEvent = 'custom_event',
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

export type BreakdownKeyType = string | number | (string | number)[] | null

export interface Breakdown {
    property: string | number
    type: BreakdownType
    normalize_url?: boolean
}

export interface FilterType {
    // used by all
    insight?: InsightType
    date_from?: string | null
    date_to?: string | null

    properties?: AnyPropertyFilter[] | PropertyGroupFilter
    events?: Record<string, any>[]
    actions?: Record<string, any>[]

    filter_test_accounts?: boolean
    from_dashboard?: boolean | number

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
    breakdown_value?: string | number
    breakdown_group_type_index?: number | null
    aggregation_group_type_index?: number | undefined // Groups aggregation
}

export interface PropertiesTimelineFilterType {
    date_from?: string | null // DateMixin
    date_to?: string | null // DateMixin
    properties?: AnyPropertyFilter[] | PropertyGroupFilter // PropertyMixin
    events?: Record<string, any>[] // EntitiesMixin
    actions?: Record<string, any>[] // EntitiesMixin
    aggregation_group_type_index?: number | undefined // GroupsAggregationMixin
}

export interface TrendsFilterType extends FilterType {
    // Specifies that we want to smooth the aggregation over the specified
    // number of intervals, e.g. for a day interval, we may want to smooth over
    // 7 days to remove weekly variation. Smoothing is performed as a moving average.
    smoothing_intervals?: number
    show_legend?: boolean // used to show/hide legend next to insights graph
    hidden_legend_keys?: Record<string, boolean | undefined> // used to toggle visibilities in table and legend
    compare?: boolean
    aggregation_axis_format?: AggregationAxisFormat // a fixed format like duration that needs calculation
    aggregation_axis_prefix?: string // a prefix to add to the aggregation axis e.g. £
    aggregation_axis_postfix?: string // a postfix to add to the aggregation axis e.g. %
    breakdown_histogram_bin_count?: number // trends breakdown histogram bin count
    formula?: any
    shown_as?: ShownAsValue
    display?: ChartDisplayType
}
export interface StickinessFilterType extends FilterType {
    compare?: boolean
    show_legend?: boolean // used to show/hide legend next to insights graph
    hidden_legend_keys?: Record<string, boolean | undefined> // used to toggle visibilities in table and legend
    stickiness_days?: number
    shown_as?: ShownAsValue
    display?: ChartDisplayType
}
export interface FunnelsFilterType extends FilterType {
    funnel_viz_type?: FunnelVizType // parameter sent to funnels API for time conversion code path
    funnel_from_step?: number // used in time to convert: initial step index to compute time to convert
    funnel_to_step?: number // used in time to convert: ending step index to compute time to convert
    funnel_step_reference?: FunnelStepReference // whether conversion shown in graph should be across all steps or just from the previous step
    funnel_step_breakdown?: string | number[] | number | null // used in steps breakdown: persons modal
    breakdown_attribution_type?: BreakdownAttributionType // funnels breakdown attribution type
    breakdown_attribution_value?: number // funnels breakdown attribution specific step value
    bin_count?: BinCountValue // used in time to convert: number of bins to show in histogram
    funnel_window_interval_unit?: FunnelConversionWindowTimeUnit // minutes, days, weeks, etc. for conversion window
    funnel_window_interval?: number | undefined // length of conversion window
    funnel_order_type?: StepOrderValue
    exclusions?: FunnelStepRangeEntityFilter[] // used in funnel exclusion filters
    funnel_correlation_person_entity?: Record<string, any> // Funnel Correlation Persons Filter
    funnel_correlation_person_converted?: 'true' | 'false' // Funnel Correlation Persons Converted - success or failure counts
    funnel_custom_steps?: number[] // used to provide custom steps for which to get people in a funnel - primarily for correlation use
    funnel_advanced?: boolean // used to toggle advanced options on or off
    layout?: FunnelLayout // used only for funnels
    funnel_step?: number
    entrance_period_start?: string // this and drop_off is used for funnels time conversion date for the persons modal
    drop_off?: boolean
    new_entity?: Record<string, any>[]
    hidden_legend_keys?: Record<string, boolean | undefined> // used to toggle visibilities in table and legend
}
export interface PathsFilterType extends FilterType {
    path_type?: PathType
    include_event_types?: PathType[]
    start_point?: string
    end_point?: string
    path_groupings?: string[]
    funnel_paths?: FunnelPathType
    funnel_filter?: Record<string, any> // Funnel Filter used in Paths
    exclude_events?: string[] // Paths Exclusion type
    step_limit?: number // Paths Step Limit
    path_start_key?: string // Paths People Start Key
    path_end_key?: string // Paths People End Key
    path_dropoff_key?: string // Paths People Dropoff Key
    path_replacements?: boolean
    local_path_cleaning_filters?: Record<string, any>[]
    edge_limit?: number | undefined // Paths edge limit
    min_edge_weight?: number | undefined // Paths
    max_edge_weight?: number | undefined // Paths
}
export interface RetentionFilterType extends FilterType {
    retention_type?: RetentionType
    retention_reference?: 'total' | 'previous' // retention wrt cohort size or previous period
    total_intervals?: number // retention total intervals
    returning_entity?: Record<string, any>
    target_entity?: Record<string, any>
    period?: string
}
export interface LifecycleFilterType extends FilterType {
    shown_as?: ShownAsValue
}
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

export type InsightEditorFilterGroup = {
    title?: string
    editorFilters: InsightEditorFilter[]
    defaultExpanded?: boolean
    count?: number
}

export interface EditorFilterProps {
    insight: Partial<InsightModel>
    insightProps: InsightLogicProps
    filters: Partial<FilterType>
    value: any
}

export interface InsightEditorFilter {
    key: string
    label?: string | ((props: EditorFilterProps) => JSX.Element | null)
    tooltip?: JSX.Element
    showOptional?: boolean
    position?: 'left' | 'right'
    valueSelector?: (insight: Partial<InsightModel>) => any
    component?: (props: EditorFilterProps) => JSX.Element | null
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
    properties?: PropertyFilter[]
    type: EntityType
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
    filter?: FilterType
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
    custom_name?: string
    order: number
    people?: string[]
    type: EntityType
    labels?: string[]
    breakdown?: BreakdownKeyType
    breakdowns?: Breakdown[]
    breakdown_value?: BreakdownKeyType
    data?: number[]
    days?: string[]

    // Url that you can GET to retrieve the people that converted in this step
    converted_people_url: string

    // Url that you can GET to retrieve the people that dropped in this step
    dropped_people_url: string
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
}

export interface HistogramGraphDatum {
    id: number
    bin0: number
    bin1: number
    count: number
    label: string
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

export type FunnelAPIResponse = FunnelStep[] | FunnelStep[][] | FunnelsTimeConversionBins

export interface LoadedRawFunnelResults {
    results: FunnelAPIResponse
    filters: Partial<FilterType>
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

export interface FlattenedFunnelStep extends FunnelStepWithConversionMetrics {
    rowKey: number | string
    nestedRowKeys?: string[]
    isBreakdownParent?: boolean
    breakdownIndex?: number
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
}

// Shared between insightLogic, dashboardItemLogic, trendsLogic, funnelLogic, pathsLogic, retentionTableLogic
export interface InsightLogicProps {
    /** currently persisted insight */
    dashboardItemId?: InsightShortId | 'new' | `new-${string}` | null
    /** id of the dashboard the insight is on (when the insight is being displayed on a dashboard) **/
    dashboardId?: DashboardType['id']
    /** cached insight */
    cachedInsight?: Partial<InsightModel> | null
    /** enable this to avoid API requests */
    doNotLoad?: boolean
}

export interface SetInsightOptions {
    /** this overrides the in-flight filters on the page, which may not equal the last returned API response */
    overrideFilter?: boolean
    /** calling with this updates the "last saved" filters */
    fromPersistentApi?: boolean
}

export interface FeatureFlagGroupType {
    properties: AnyPropertyFilter[]
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
}

export interface FeatureFlagType {
    id: number | null
    key: string
    name: string // Used as description
    filters: FeatureFlagFilters
    deleted: boolean
    active: boolean
    created_by: UserBasicType | null
    created_at: string | null
    is_simple_flag: boolean
    rollout_percentage: number | null
    ensure_experience_continuity: boolean | null
    experiment_set: string[] | null
    rollback_conditions: FeatureFlagRollbackConditions[]
    performed_rollback: boolean
    can_edit: boolean
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
    debug_queries: boolean
    /** Whether debug queries option should be shown on the command palette. */
    disable_paid_fs: boolean /** Whether paid features showcasing / upsells are completely disabled throughout the app. */
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
    posthog_version?: string
    email_service_available: boolean
    slack_service: {
        available: boolean
        client_id?: string
    }
    /** Whether PostHog is running in DEBUG mode. */
    is_debug?: boolean
    is_event_property_usage_enabled?: boolean
    licensed_users_available?: number | null
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
    Public = 'public', // When viewing the dashboard publicly
    Export = 'export', // When the dashboard is being exported (alike to being printed)
}

export enum DashboardMode { // Default mode is null
    Edit = 'edit', // When the dashboard is being edited
    Fullscreen = 'fullscreen', // When the dashboard is on full screen (presentation) mode
    Sharing = 'sharing', // When the sharing configuration is opened
}

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
    | 'enter'
    | ' '
    | 'arrowleft'
    | 'arrowright'
    | 'arrowdown'
    | 'arrowup'

export interface LicenseType {
    id: number
    plan: LicensePlan
    valid_until: string
    created_at: string
}

export interface EventDefinition {
    id: string
    name: string
    description?: string
    tags?: string[]
    volume_30_day?: number | null
    query_usage_30_day?: number | null
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

export interface PropertyDefinition {
    id: string
    name: string
    description?: string
    tags?: string[]
    volume_30_day?: number | null // TODO: Deprecated, replace or remove
    query_usage_30_day?: number | null
    updated_at?: string
    updated_by?: UserBasicType | null
    is_numerical?: boolean // Marked as optional to allow merge of EventDefinition & PropertyDefinition
    is_event_property?: boolean // Indicates whether this property has been seen for a particular set of events (when `eventNames` query string is sent); calculated at query time, not stored in the db
    property_type?: PropertyType
    created_at?: string // TODO: Implement
    last_seen_at?: string // TODO: Implement
    example?: string
    is_action?: boolean
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
    // ID of feature flag
    feature_flag?: number
    filters: FilterType
    parameters: {
        minimum_detectable_effect?: number
        recommended_running_time?: number
        recommended_sample_size?: number
        feature_flag_variants: MultivariateFlagVariant[]
    }
    start_date?: string | null
    end_date?: string | null
    archived?: boolean
    secondary_metrics: SecondaryExperimentMetric[]
    created_at: string
    created_by: UserBasicType | null
}

export interface ExperimentResults {
    insight: FunnelStep[][] | TrendResult[]
    probability: Record<string, number>
    filters: FilterType
    itemID: string
    significant: boolean
    noData?: boolean
    significance_code: SignificanceCode
    expected_loss?: number
    p_value?: number
    secondary_metric_results?: SecondaryMetricResult[]
}

export interface SecondaryMetricResult {
    name: string
    result: Record<string, number>
}

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
    current_team: TeamType | null
    preflight: PreflightStatus
    default_event_name: string
    persisted_feature_flags?: string[]
    anonymous: boolean
    frontend_apps?: Record<number, FrontendAppConfig>
    /** Whether the user was autoswitched to the current item's team. */
    switched_team: TeamType['id'] | null
    /** First day of the week (0 = Sun, 1 = Mon, ...) */
    week_start: number

    year_in_hog_url?: string
}

export type StoredMetricMathOperations = 'max' | 'min' | 'sum'

export interface PathEdgeParameters {
    edge_limit?: number | undefined
    min_edge_weight?: number | undefined
    max_edge_weight?: number | undefined
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

export enum SignificanceCode {
    Significant = 'significant',
    NotEnoughExposure = 'not_enough_exposure',
    LowWinProbability = 'low_win_probability',
    HighLoss = 'high_loss',
    HighPValue = 'high_p_value',
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

export enum HelpType {
    Slack = 'slack',
    GitHub = 'github',
    Email = 'email',
    Docs = 'docs',
}

export interface VersionType {
    version: string
    release_date?: string
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
    /** Whether to show a custom popup */
    popup?: (close: () => void) => React.ReactNode
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

export type ExportContext = OnlineExportContext | LocalExportContext

export interface ExportedAssetType {
    id: number
    export_format: ExporterFormat
    dashboard?: number
    insight?: number
    export_context?: ExportContext
    has_content: boolean
    filename: string
}

export enum YesOrNoResponse {
    Yes = 'yes',
    No = 'no',
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
    feature_flag: FeatureFlagType
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
