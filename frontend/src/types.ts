import {
    ACTION_TYPE,
    AUTOCAPTURE,
    CUSTOM_EVENT,
    EVENT_TYPE,
    OrganizationMembershipLevel,
    PAGEVIEW,
    SCREEN,
    ShownAsValue,
} from 'lib/constants'
import { PluginConfigSchema } from '@posthog/plugin-scaffold'
import { PluginInstallationType } from 'scenes/plugins/types'
import { ViewType } from 'scenes/insights/insightLogic'

export interface UserType {
    anonymize_data: boolean
    distinct_id: string
    email: string
    email_opt_in: boolean
    id: number
    name: string
    posthog_version: string
    organization: OrganizationType | null
    team: TeamType | null
    toolbar_mode: 'disabled' | 'toolbar'
    organizations: OrganizationType[]
    teams: TeamType[]
    current_organization_id: string
    current_team_id: number
    plugin_access: PluginAccess
    has_password: boolean
    is_multi_tenancy: boolean
    is_staff: boolean
    is_debug: boolean
    is_impersonated: boolean
    ee_enabled: boolean
    email_service_available: boolean
    realm: 'cloud' | 'hosted'
    billing?: OrganizationBilling
}

/* Type for User objects in nested serializers (e.g. created_by) */
export interface UserNestedType {
    id: number
    distinct_id: string
    first_name: string
    email: string
}

export interface UserUpdateType {
    user?: Omit<Partial<UserType>, 'team'>
    team?: Partial<TeamType>
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

export interface OrganizationType {
    id: string
    name: string
    created_at: string
    updated_at: boolean
    available_features: string[]
    billing_plan: string
    billing: OrganizationBilling
    teams?: TeamType[]
    membership_level: OrganizationMembershipLevel | null
    setup: SetupState
    personalization: PersonalizationData
}

export interface OrganizationMemberType {
    joined_at: string
    level: OrganizationMembershipLevel
    membership_id: string
    updated_at: string
    user_email: string
    user_first_name: string
    user_id: number
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

export interface TeamType {
    id: number
    name: string
    anonymize_ips: boolean
    api_token: string
    app_urls: string[]
    completed_snippet_onboarding: boolean
    event_names: string[]
    event_properties: string[]
    event_properties_numerical: string[]
    event_names_with_usage: EventUsageType[]
    event_properties_with_usage: PropertyUsageType[]
    slack_incoming_webhook: string
    session_recording_opt_in: boolean
    session_recording_retention_period_days: number | null
    plugins_opt_in: boolean
    ingested_event: boolean
    is_demo: boolean
}

export interface ActionType {
    count?: number
    created_at: string
    deleted?: boolean
    id: number
    is_calculating?: boolean
    name: string
    post_to_slack?: boolean
    steps?: ActionStepType[]
    created_by: Record<string, any>
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
    url_matching?: 'contains' | 'regex' | 'exact'
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
}

export interface PropertyFilter {
    key: string
    operator: string | null
    type: string
    value: string | number
}

interface BasePropertyFilter {
    key: string
    value: string | number | null
    label?: string
}

export type PropertyOperator =
    | 'exact'
    | 'is_not'
    | 'icontains'
    | 'not_icontains'
    | 'regex'
    | 'not_regex'
    | 'gt'
    | 'lt'
    | 'is_set'
    | 'is_not_set'

interface EventPropertyFilter extends BasePropertyFilter {
    type: 'event'
    operator: PropertyOperator
}

export interface PersonPropertyFilter extends BasePropertyFilter {
    type: 'person'
    operator: PropertyOperator
}

interface CohortPropertyFilter extends BasePropertyFilter {
    type: 'cohort'
}

interface RecordingDurationFilter extends BasePropertyFilter {
    type: 'recording'
    key: 'duration'
    value: number
    operator: 'lt' | 'gt'
}

interface RecordingNotViewedFilter extends BasePropertyFilter {
    type: 'recording'
    key: 'unseen'
}

export type RecordingPropertyFilter = RecordingDurationFilter | RecordingNotViewedFilter

interface ActionTypePropertyFilter extends BasePropertyFilter {
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

export type EntityType = 'actions' | 'events'

export interface Entity {
    id: string | number
    name: string
    order: number
    type: EntityType
}

export interface EntityWithProperties extends Entity {
    properties: Record<string, any>
}

export interface PersonType {
    id: number
    uuid: string
    name: string
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
    created_by?: Record<string, any>
    created_at?: string
    deleted?: boolean
    id: number
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

export interface FormattedNumber {
    // :TODO: DEPRECATED, formatting will now happen client-side
    value: number
    formatted: string
}

export interface OrganizationBilling {
    plan: PlanInterface | null
    current_usage: FormattedNumber | number | null
    should_setup_billing?: boolean
    stripe_checkout_session?: string
    subscription_url?: string
    event_allocation: FormattedNumber | number | null
}

export interface PlanInterface {
    key: string
    name: string
    custom_setup_billing_message: string
    image_url: string
    self_serve: boolean
    is_metered_billing: boolean
    allowance: FormattedNumber | number | null // :TODO: DEPRECATED
    event_allowance: number
    price_string: string
}

export interface BillingSubscription {
    subscription_url: string
    stripe_checkout_session: string
}

export interface DashboardItemType {
    id: number
    name: string
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
    created_by: Record<string, any>
    is_sample: boolean
    dashboard: number
    result: any | null
}

export interface DashboardType {
    id: number
    name: string
    pinned: boolean
    items: DashboardItemType[]
    created_at: string
    created_by: number
    is_shared: boolean
    share_token: string
    deleted: boolean
    filters: Record<string, any>
}

export interface OrganizationInviteType {
    id: string
    target_email: string
    is_expired: boolean
    emailing_attempt_made: boolean
    created_by: UserNestedType | null
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
}

export interface PluginConfigType {
    id?: number
    plugin: number
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

export interface AnnotationType {
    id: string
    scope: 'organization' | 'dashboard_item'
    content: string
    date_marker: string
    created_by?: UserNestedType | null
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
    | 'PathsViz'
    | 'FunnelViz'
export type InsightType = 'TRENDS' | 'SESSIONS' | 'FUNNELS' | 'RETENTION' | 'PATHS' | 'LIFECYCLE' | 'STICKINESS'
export type ShownAsType = ShownAsValue // DEPRECATED: Remove when releasing `remove-shownas`
export type BreakdownType = 'cohort' | 'person' | 'event'
export type PathType = typeof PAGEVIEW | typeof AUTOCAPTURE | typeof SCREEN | typeof CUSTOM_EVENT
export type RetentionType = 'retention_recurring' | 'retention_first_time'

export interface FilterType {
    insight: InsightType
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
    returningEntity?: Record<string, any>
    startEntity?: Record<string, any>
    path_type?: PathType
    start_point?: string | number
    stickiness_days?: number
    entity_id?: string | number
    entity_type?: EntityType
    people_day?: any
    people_action?: any
    formula?: any
}

export interface SystemStatus {
    metric: string
    value: string
    key?: string
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
    django: boolean
    plugins: boolean
    redis: boolean
    db: boolean
    initiated: boolean
    cloud: boolean
    celery: boolean
    available_social_auth_providers: AuthBackends
}
