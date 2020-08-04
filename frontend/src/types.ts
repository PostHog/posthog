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
    toolbar_mode: string
}

export interface TeamType {
    anonymize_ips: boolean
    api_token: string
    app_urls: string[]
    completed_snippet_onboarding: boolean
    event_names: string[]
    event_properties: string[]
    opt_out_capture: boolean
    signup_token: string
    slack_incoming_webhook: string
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

export type EditorProps = {
    apiURL?: string
    jsURL?: string
    temporaryToken?: string
    actionId?: number
    userIntent?: string
    instrument?: boolean
    distinctId?: boolean
    userEmail?: boolean
}
