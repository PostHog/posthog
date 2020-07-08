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
