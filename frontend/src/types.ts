export interface UserType {
    anonymize_data: boolean
    distinct_id: string
    email: string
    email_opt_in: boolean
    has_events: boolean
    id: number
    name: string
    opt_out_capture: null
    posthog_version: string
    team: TeamType
    toolbar_mode: 'disabled' | 'toolbar'
    billing: OrganizationBilling
}

export interface UserUpdateType extends Omit<Partial<UserType>, 'team'> {
    team: Partial<TeamType>
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

export interface TeamType {
    anonymize_ips: boolean
    api_token: string
    app_urls: string[]
    completed_snippet_onboarding: boolean
    event_names: string[]
    event_properties: string[]
    event_properties_numerical: string[]
    opt_out_capture: boolean
    signup_token: string
    slack_incoming_webhook: string
    session_recording_opt_in: boolean
}

export interface ActionType {
    count?: number
    created_at?: string
    deleted?: boolean
    id?: number
    is_calculating?: boolean
    name?: string
    post_to_slack?: boolean
    steps?: ActionStepType[]
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

export type ToolbarTab = 'stats' | 'actions'
export type ToolbarMode = 'button' | 'dock' | ''
export type ToolbarAnimationState = 'animating' | 'fading-in' | 'complete' | 'disabled' | 'fading-out'
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

export interface CohortType {
    count?: number
    created_by?: Record<string, any>
    created_at?: string
    deleted?: boolean
    id: number
    is_calculating?: boolean
    last_calculation?: string
    name?: string
    groups?: Record<string, any>[]
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
