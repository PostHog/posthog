import { OrganizationMembershipLevel } from 'lib/constants'
import { PluginConfigSchema } from '@posthog/plugin-scaffold'
import { PluginInstallationType } from 'scenes/plugins/types'
export interface UserType {
    anonymize_data: boolean
    distinct_id: string
    email: string
    email_opt_in: boolean
    id: number
    name: string
    opt_out_capture: null
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
    teams: TeamType[]
    membership_level: OrganizationMembershipLevel | null
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
    opt_out_capture: boolean
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
    type: 'action_type'
    properties?: Array<EventPropertyFilter>
}

export interface EventTypePropertyFilter extends BasePropertyFilter {
    type: 'event_type'
    properties?: Array<EventPropertyFilter>
}

export type SessionsPropertyFilter =
    | PersonPropertyFilter
    | CohortPropertyFilter
    | RecordingPropertyFilter
    | ActionTypePropertyFilter
    | EventTypePropertyFilter

export interface Entity {
    id: string | number
    name: string
    order: number
    type: 'actions' | 'events'
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

export interface CohortType {
    count?: number
    created_by?: Record<string, any>
    created_at?: string
    deleted?: boolean
    id: number
    is_calculating?: boolean
    last_calculation?: string
    name?: string
    csv?: File
    groups: Record<string, any>[]
}

export interface InsightHistory {
    id: number
    filters: Record<string, any>
    name?: string
    createdAt: string
    saved: boolean
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

export interface OrganizationBilling {
    plan: PlanInterface
    current_usage: { value: number; formatted: string } | null
    should_setup_billing: boolean
    stripe_checkout_session: string
    subscription_url: string
}

export interface PlanInterface {
    key: string
    name: string
    custom_setup_billing_message: string
    image_url: string
    self_serve: boolean
    allowance: null | Record<string, string | number>
}

export interface BillingSubscription {
    subscription_url: string
    stripe_checkout_session: string
}

export interface DashboardItemType {
    id: number
    name: string
    filters: Record<string, any>
    filters_hash: string
    order: number
    deleted: boolean
    saved: boolean
    created_at: string
    layouts: Record<string, any>
    color: string
    last_refresh: string
    refreshing: boolean
    created_by: Record<string, any>
    is_sample: boolean
}

export interface DashboardType {
    id: number
    name: string
    pinned: string
    items: DashboardItemType[]
    created_at: string
    created_by: number
    is_shared: boolean
    share_token: string
    deleted: boolean
}

export interface OrganizationInviteType {
    created_at: string
    created_by_email: string
    created_by_first_name: string
    created_by_id: number
    emailing_attempt_made: boolean
    id: string
    target_email: string
    updated_at: string
    is_expired: boolean
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
    error?: PluginErrorType
    maintainer?: string
}

export interface PluginConfigType {
    id?: number
    plugin: number
    enabled: boolean
    order: number
    config: Record<string, any>
    global?: boolean
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

export interface FilterType {
    insight: 'TRENDS' | 'SESSIONS' | 'FUNNELS' | 'RETENTION' | 'PATHS' | 'LIFECYCLE' | 'STICKINESS'
    display?:
        | 'ActionsLineGraph'
        | 'ActionsLineGraphCumulative'
        | 'ActionsTable'
        | 'ActionsPie'
        | 'ActionsBar'
        | 'PathsViz'
        | 'FunnelViz'
    interval?: string
    date_from?: string
    date_to?: string
    properties?: PropertyFilter[]
    events?: Record<string, any>[]
    actions?: Record<string, any>[]
    breakdown_type?: 'cohort' | 'person' | 'event'
    shown_as?: 'Volume' | 'Stickiness' | 'Lifecycle' // DEPRECATED: Remove when releasing `remove-shownas`
    session?: string
    period?: string
    retentionType?: 'retention_recurring' | 'retention_first_time'
    returningEntity?: Record<string, any>
    startEntity?: Record<string, any>
    path_type?: '$pageview' | '$screen' | '$autocapture' | 'custom_event'
}

export interface SystemStatus {
    metric: string
    value: string
    key?: string
}
