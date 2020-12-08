import { OrganizationMembershipLevel } from 'lib/constants'
import { PluginConfigSchema } from 'posthog-plugins'
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
    email_service_available: boolean
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
    plugins_opt_in: boolean
    ingested_event: boolean
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

export interface Entity {
    id: string | number
    name: string
    order: number
    type: string
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
    groups: Record<string, any>[]
}

export interface InsightHistory {
    id: number
    type: string
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
    id: number
    properties: Record<string, any>
    timestamp: string
}

export interface SessionType {
    distinct_id: string
    event_count: number
    events: EventType[]
    global_session_id: string
    length: number
    properties: Record<string, any>
    start_time: string
    end_time: string
    session_recording_ids: string[]
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

export interface DashboardType {
    id: number
    name: string
    pinned: string
    items: []
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
    name: string
    description: string
    url: string
    tag: string
    config_schema: Record<string, PluginConfigSchema> | PluginConfigSchema[]
    error?: PluginErrorType
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
