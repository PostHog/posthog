/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - core
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

export interface CIMDVerificationTokenApi {
    readonly id: string
    /** @maxLength 40 */
    label: string
    /** @nullable */
    readonly mask_value: string | null
    readonly created_by: UserBasicApi
    readonly created_at: string
    /** @nullable */
    readonly last_used_at: string | null
}

export interface PaginatedCIMDVerificationTokenListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CIMDVerificationTokenApi[]
}

/**
 * Create-response variant that includes the plaintext token.
 *
 * Only emitted from the create endpoint - storage-side we only persist the
 * hash, so subsequent reads use the base serializer.
 */
export interface CIMDVerificationTokenWithValueApi {
    readonly id: string
    /** @maxLength 40 */
    label: string
    /** @nullable */
    readonly mask_value: string | null
    readonly created_by: UserBasicApi
    readonly created_at: string
    /** @nullable */
    readonly last_used_at: string | null
    /** Plaintext token, only returned on creation */
    readonly value: string
}

export interface OrganizationDomainApi {
    readonly id: string
    /** @maxLength 128 */
    domain: string
    /** Determines whether a domain is verified or not. */
    readonly is_verified: boolean
    /** @nullable */
    readonly verified_at: string | null
    readonly verification_challenge: string
    jit_provisioning_enabled?: boolean
    /** @maxLength 28 */
    sso_enforcement?: string
    /** Returns whether SAML is configured for the instance. Does not validate the user has the required license (that check is performed in other places). */
    readonly has_saml: boolean
    /**
     * SAML IdP entity ID (issuer).
     * @maxLength 512
     * @nullable
     */
    saml_entity_id?: string | null
    /**
     * SAML single sign-on (ACS) URL.
     * @maxLength 512
     * @nullable
     */
    saml_acs_url?: string | null
    /**
     * SAML IdP X.509 signing certificate (PEM).
     * @nullable
     */
    saml_x509_cert?: string | null
    /** Returns whether SCIM is configured and enabled for this domain. */
    readonly has_scim: boolean
    /** Whether SCIM provisioning is enabled for this domain. */
    scim_enabled?: boolean
    /** @nullable */
    readonly scim_base_url: string | null
    /** @nullable */
    readonly scim_bearer_token: string | null
    /** Returns whether ID-JAG (XAA) is configured for this domain. */
    readonly has_id_jag: boolean
    /**
     * Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG on this domain.
     * @maxLength 512
     * @nullable
     */
    id_jag_issuer_url?: string | null
    /**
     * Override JWKS URL. Defaults to OIDC discovery on the issuer URL.
     * @maxLength 512
     * @nullable
     */
    id_jag_jwks_url?: string | null
    /**
     * Allowed ID-JAG client IDs. Empty list allows any client_id.
     * @items.maxLength 256
     */
    id_jag_allowed_clients?: string[]
    /**
     * Linked IdP configuration (SAML/SCIM/XAA) that backs this domain. Must belong to the same organization.
     * @nullable
     */
    identity_provider_config?: string | null
}

export interface PaginatedOrganizationDomainListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: OrganizationDomainApi[]
}

export interface PatchedOrganizationDomainApi {
    readonly id?: string
    /** @maxLength 128 */
    domain?: string
    /** Determines whether a domain is verified or not. */
    readonly is_verified?: boolean
    /** @nullable */
    readonly verified_at?: string | null
    readonly verification_challenge?: string
    jit_provisioning_enabled?: boolean
    /** @maxLength 28 */
    sso_enforcement?: string
    /** Returns whether SAML is configured for the instance. Does not validate the user has the required license (that check is performed in other places). */
    readonly has_saml?: boolean
    /**
     * SAML IdP entity ID (issuer).
     * @maxLength 512
     * @nullable
     */
    saml_entity_id?: string | null
    /**
     * SAML single sign-on (ACS) URL.
     * @maxLength 512
     * @nullable
     */
    saml_acs_url?: string | null
    /**
     * SAML IdP X.509 signing certificate (PEM).
     * @nullable
     */
    saml_x509_cert?: string | null
    /** Returns whether SCIM is configured and enabled for this domain. */
    readonly has_scim?: boolean
    /** Whether SCIM provisioning is enabled for this domain. */
    scim_enabled?: boolean
    /** @nullable */
    readonly scim_base_url?: string | null
    /** @nullable */
    readonly scim_bearer_token?: string | null
    /** Returns whether ID-JAG (XAA) is configured for this domain. */
    readonly has_id_jag?: boolean
    /**
     * Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG on this domain.
     * @maxLength 512
     * @nullable
     */
    id_jag_issuer_url?: string | null
    /**
     * Override JWKS URL. Defaults to OIDC discovery on the issuer URL.
     * @maxLength 512
     * @nullable
     */
    id_jag_jwks_url?: string | null
    /**
     * Allowed ID-JAG client IDs. Empty list allows any client_id.
     * @items.maxLength 256
     */
    id_jag_allowed_clients?: string[]
    /**
     * Linked IdP configuration (SAML/SCIM/XAA) that backs this domain. Must belong to the same organization.
     * @nullable
     */
    identity_provider_config?: string | null
}

export interface IdentityProviderConfigApi {
    readonly id: string
    /**
     * Display name for this IdP configuration (e.g. 'Okta production').
     * @maxLength 255
     */
    name?: string
    readonly created_at: string
    readonly updated_at: string
    /** Whether SAML is fully configured on this config. */
    readonly has_saml: boolean
    /**
     * SAML IdP entity ID (issuer).
     * @maxLength 512
     * @nullable
     */
    saml_entity_id?: string | null
    /**
     * SAML single sign-on (ACS) URL the IdP redirects to.
     * @maxLength 512
     * @nullable
     */
    saml_acs_url?: string | null
    /**
     * SAML IdP X.509 signing certificate (PEM).
     * @nullable
     */
    saml_x509_cert?: string | null
    /** Whether SCIM is enabled and a bearer token is set on this config. */
    readonly has_scim: boolean
    /** Whether SCIM provisioning is enabled. Setting this true generates a bearer token (returned once); setting it false clears the token. */
    scim_enabled?: boolean
    /**
     * Plaintext SCIM bearer token. Only returned once, immediately after SCIM is enabled or the token is regenerated; null otherwise.
     * @nullable
     */
    readonly scim_bearer_token: string | null
    /** Whether ID-JAG (XAA) is configured on this config. */
    readonly has_id_jag: boolean
    /**
     * Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG.
     * @maxLength 512
     * @nullable
     */
    id_jag_issuer_url?: string | null
    /**
     * Override JWKS URL. Defaults to OIDC discovery on the issuer URL.
     * @maxLength 512
     * @nullable
     */
    id_jag_jwks_url?: string | null
    /**
     * Allowed ID-JAG client IDs. Empty list allows any client_id.
     * @items.maxLength 256
     */
    id_jag_allowed_clients?: string[]
}

export interface PaginatedIdentityProviderConfigListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: IdentityProviderConfigApi[]
}

export interface PatchedIdentityProviderConfigApi {
    readonly id?: string
    /**
     * Display name for this IdP configuration (e.g. 'Okta production').
     * @maxLength 255
     */
    name?: string
    readonly created_at?: string
    readonly updated_at?: string
    /** Whether SAML is fully configured on this config. */
    readonly has_saml?: boolean
    /**
     * SAML IdP entity ID (issuer).
     * @maxLength 512
     * @nullable
     */
    saml_entity_id?: string | null
    /**
     * SAML single sign-on (ACS) URL the IdP redirects to.
     * @maxLength 512
     * @nullable
     */
    saml_acs_url?: string | null
    /**
     * SAML IdP X.509 signing certificate (PEM).
     * @nullable
     */
    saml_x509_cert?: string | null
    /** Whether SCIM is enabled and a bearer token is set on this config. */
    readonly has_scim?: boolean
    /** Whether SCIM provisioning is enabled. Setting this true generates a bearer token (returned once); setting it false clears the token. */
    scim_enabled?: boolean
    /**
     * Plaintext SCIM bearer token. Only returned once, immediately after SCIM is enabled or the token is regenerated; null otherwise.
     * @nullable
     */
    readonly scim_bearer_token?: string | null
    /** Whether ID-JAG (XAA) is configured on this config. */
    readonly has_id_jag?: boolean
    /**
     * Trusted IdP issuer URL for ID-JAG (XAA). Required to enable ID-JAG.
     * @maxLength 512
     * @nullable
     */
    id_jag_issuer_url?: string | null
    /**
     * Override JWKS URL. Defaults to OIDC discovery on the issuer URL.
     * @maxLength 512
     * @nullable
     */
    id_jag_jwks_url?: string | null
    /**
     * Allowed ID-JAG client IDs. Empty list allows any client_id.
     * @items.maxLength 256
     */
    id_jag_allowed_clients?: string[]
}

export interface SCIMTokenResponseApi {
    /** Whether SCIM is enabled for this config. */
    scim_enabled: boolean
    /** Newly generated plaintext SCIM bearer token. Only returned once. */
    scim_bearer_token: string
}

/**
 * * `1` - member
 * * `8` - administrator
 * * `15` - owner
 */
export type OrganizationMembershipLevelEnumApi =
    (typeof OrganizationMembershipLevelEnumApi)[keyof typeof OrganizationMembershipLevelEnumApi]

export const OrganizationMembershipLevelEnumApi = {
    Number1: 1,
    Number8: 8,
    Number15: 15,
} as const

export interface OrganizationInviteApi {
    readonly id: string
    /** @maxLength 254 */
    target_email: string
    /** @maxLength 30 */
    first_name?: string
    readonly emailing_attempt_made: boolean
    level?: OrganizationMembershipLevelEnumApi
    /** Check if invite is older than INVITE_DAYS_VALIDITY days. */
    readonly is_expired: boolean
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    /** @nullable */
    message?: string | null
    /** List of team IDs and corresponding access levels to private projects. */
    private_project_access?: unknown
    send_email?: boolean
    combine_pending_invites?: boolean
}

export interface PaginatedOrganizationInviteListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: OrganizationInviteApi[]
}

export interface OrganizationInviteDelegateApi {
    /** Email of the teammate who should complete setup on the inviter's behalf. Receives a PostHog-branded delegation invite granting admin-level membership on accept. */
    target_email: string
    /**
     * Optional personal message included in the delegation email (up to 1000 characters).
     * @maxLength 1000
     */
    message?: string
    /**
     * Onboarding step key the delegator was on when delegating, for analytics only.
     * @maxLength 64
     */
    step_at_delegation?: string
}

/**
 * Serializer for organization-scoped OAuth applications (read-only).
 */
export interface OrganizationOAuthApplicationApi {
    readonly id: string
    /** @maxLength 255 */
    name?: string
    /** @maxLength 100 */
    client_id?: string
    readonly redirect_uris_list: readonly string[]
    /** True if this application has been verified by PostHog */
    is_verified?: boolean
    readonly created: string
    readonly updated: string
}

export interface PaginatedOrganizationOAuthApplicationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: OrganizationOAuthApplicationApi[]
}

/**
 * Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of
 * passthrough fields. This allows the meaning of `Team` to change from "project" to "environment" without breaking
 * backward compatibility of the REST API.
 * Do not use this in greenfield endpoints!
 */
export interface ProjectBackwardCompatBasicApi {
    readonly id: number
    readonly uuid: string
    readonly organization: string
    /** ID of the project this environment belongs to. */
    readonly project_id: number
    readonly api_token: string
    readonly name: string
    readonly completed_snippet_onboarding: boolean
    readonly has_completed_onboarding_for: unknown
    readonly ingested_event: boolean
    readonly is_demo: boolean
    readonly timezone: string
    readonly access_control: boolean
}

export interface PaginatedProjectBackwardCompatBasicListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ProjectBackwardCompatBasicApi[]
}

export type ProjectBackwardCompatApiGroupTypesItem = { [key: string]: unknown }

export type ProjectBackwardCompatApiDefaultModifiers = { [key: string]: unknown }

export type ProjectBackwardCompatApiProductIntentsItem = {
    product_type?: string
    created_at?: string
    /** @nullable */
    onboarding_completed_at?: string | null
    updated_at?: string
}

export type ProjectBackwardCompatApiManagedViewsets = { [key: string]: boolean }

export type EffectiveMembershipLevelEnumApi =
    (typeof EffectiveMembershipLevelEnumApi)[keyof typeof EffectiveMembershipLevelEnumApi]

export const EffectiveMembershipLevelEnumApi = {
    Number1: 1,
    Number8: 8,
    Number15: 15,
} as const

/**
 * * `30d` - 30 Days
 * * `90d` - 90 Days
 * * `1y` - 1 Year
 * * `5y` - 5 Years
 */
export type SessionRecordingRetentionPeriodEnumApi =
    (typeof SessionRecordingRetentionPeriodEnumApi)[keyof typeof SessionRecordingRetentionPeriodEnumApi]

export const SessionRecordingRetentionPeriodEnumApi = {
    '30d': '30d',
    '90d': '90d',
    '1y': '1y',
    '5y': '5y',
} as const

/**
 * * `0` - Sunday
 * * `1` - Monday
 */
export type WeekStartDayEnumApi = (typeof WeekStartDayEnumApi)[keyof typeof WeekStartDayEnumApi]

export const WeekStartDayEnumApi = {
    Number0: 0,
    Number1: 1,
} as const

/**
 * * `b2b` - B2B
 * * `b2c` - B2C
 * * `other` - Other
 */
export type BusinessModelEnumApi = (typeof BusinessModelEnumApi)[keyof typeof BusinessModelEnumApi]

export const BusinessModelEnumApi = {
    B2b: 'b2b',
    B2c: 'b2c',
    Other: 'other',
} as const

/**
 * * `ingest_first_event` - ingest_first_event
 * * `set_up_reverse_proxy` - set_up_reverse_proxy
 * * `create_first_insight` - create_first_insight
 * * `create_first_dashboard` - create_first_dashboard
 * * `track_custom_events` - track_custom_events
 * * `define_actions` - define_actions
 * * `set_up_cohorts` - set_up_cohorts
 * * `explore_trends_insight` - explore_trends_insight
 * * `create_funnel` - create_funnel
 * * `explore_retention_insight` - explore_retention_insight
 * * `explore_paths_insight` - explore_paths_insight
 * * `explore_stickiness_insight` - explore_stickiness_insight
 * * `explore_lifecycle_insight` - explore_lifecycle_insight
 * * `add_authorized_domain` - add_authorized_domain
 * * `set_up_web_vitals` - set_up_web_vitals
 * * `review_web_analytics_dashboard` - review_web_analytics_dashboard
 * * `filter_web_analytics` - filter_web_analytics
 * * `set_up_web_analytics_conversion_goals` - set_up_web_analytics_conversion_goals
 * * `visit_web_vitals_dashboard` - visit_web_vitals_dashboard
 * * `setup_session_recordings` - setup_session_recordings
 * * `watch_session_recording` - watch_session_recording
 * * `configure_recording_settings` - configure_recording_settings
 * * `create_recording_playlist` - create_recording_playlist
 * * `enable_console_logs` - enable_console_logs
 * * `create_feature_flag` - create_feature_flag
 * * `implement_flag_in_code` - implement_flag_in_code
 * * `update_feature_flag_release_conditions` - update_feature_flag_release_conditions
 * * `create_multivariate_flag` - create_multivariate_flag
 * * `set_up_flag_payloads` - set_up_flag_payloads
 * * `set_up_flag_evaluation_runtimes` - set_up_flag_evaluation_runtimes
 * * `create_experiment` - create_experiment
 * * `implement_experiment_variants` - implement_experiment_variants
 * * `launch_experiment` - launch_experiment
 * * `review_experiment_results` - review_experiment_results
 * * `create_survey` - create_survey
 * * `launch_survey` - launch_survey
 * * `collect_survey_responses` - collect_survey_responses
 * * `connect_source` - connect_source
 * * `run_first_query` - run_first_query
 * * `join_external_data` - join_external_data
 * * `create_saved_view` - create_saved_view
 * * `enable_error_tracking` - enable_error_tracking
 * * `upload_source_maps` - upload_source_maps
 * * `view_first_error` - view_first_error
 * * `resolve_first_error` - resolve_first_error
 * * `ingest_first_llm_event` - ingest_first_llm_event
 * * `view_first_trace` - view_first_trace
 * * `track_costs` - track_costs
 * * `set_up_llm_evaluation` - set_up_llm_evaluation
 * * `run_ai_playground` - run_ai_playground
 * * `enable_revenue_analytics_viewset` - enable_revenue_analytics_viewset
 * * `connect_revenue_source` - connect_revenue_source
 * * `set_up_revenue_goal` - set_up_revenue_goal
 * * `enable_log_capture` - enable_log_capture
 * * `view_first_logs` - view_first_logs
 * * `create_first_workflow` - create_first_workflow
 * * `set_up_first_workflow_channel` - set_up_first_workflow_channel
 * * `configure_workflow_trigger` - configure_workflow_trigger
 * * `add_workflow_action` - add_workflow_action
 * * `launch_workflow` - launch_workflow
 * * `create_first_endpoint` - create_first_endpoint
 * * `configure_endpoint` - configure_endpoint
 * * `test_endpoint` - test_endpoint
 * * `create_early_access_feature` - create_early_access_feature
 * * `update_feature_stage` - update_feature_stage
 * * `use_posthog_ai` - use_posthog_ai
 * * `use_posthog_code` - use_posthog_code
 * * `use_posthog_mcp` - use_posthog_mcp
 * * `use_posthog_in_slack` - use_posthog_in_slack
 */
export type AvailableSetupTaskIdsEnumApi =
    (typeof AvailableSetupTaskIdsEnumApi)[keyof typeof AvailableSetupTaskIdsEnumApi]

export const AvailableSetupTaskIdsEnumApi = {
    IngestFirstEvent: 'ingest_first_event',
    SetUpReverseProxy: 'set_up_reverse_proxy',
    CreateFirstInsight: 'create_first_insight',
    CreateFirstDashboard: 'create_first_dashboard',
    TrackCustomEvents: 'track_custom_events',
    DefineActions: 'define_actions',
    SetUpCohorts: 'set_up_cohorts',
    ExploreTrendsInsight: 'explore_trends_insight',
    CreateFunnel: 'create_funnel',
    ExploreRetentionInsight: 'explore_retention_insight',
    ExplorePathsInsight: 'explore_paths_insight',
    ExploreStickinessInsight: 'explore_stickiness_insight',
    ExploreLifecycleInsight: 'explore_lifecycle_insight',
    AddAuthorizedDomain: 'add_authorized_domain',
    SetUpWebVitals: 'set_up_web_vitals',
    ReviewWebAnalyticsDashboard: 'review_web_analytics_dashboard',
    FilterWebAnalytics: 'filter_web_analytics',
    SetUpWebAnalyticsConversionGoals: 'set_up_web_analytics_conversion_goals',
    VisitWebVitalsDashboard: 'visit_web_vitals_dashboard',
    SetupSessionRecordings: 'setup_session_recordings',
    WatchSessionRecording: 'watch_session_recording',
    ConfigureRecordingSettings: 'configure_recording_settings',
    CreateRecordingPlaylist: 'create_recording_playlist',
    EnableConsoleLogs: 'enable_console_logs',
    CreateFeatureFlag: 'create_feature_flag',
    ImplementFlagInCode: 'implement_flag_in_code',
    UpdateFeatureFlagReleaseConditions: 'update_feature_flag_release_conditions',
    CreateMultivariateFlag: 'create_multivariate_flag',
    SetUpFlagPayloads: 'set_up_flag_payloads',
    SetUpFlagEvaluationRuntimes: 'set_up_flag_evaluation_runtimes',
    CreateExperiment: 'create_experiment',
    ImplementExperimentVariants: 'implement_experiment_variants',
    LaunchExperiment: 'launch_experiment',
    ReviewExperimentResults: 'review_experiment_results',
    CreateSurvey: 'create_survey',
    LaunchSurvey: 'launch_survey',
    CollectSurveyResponses: 'collect_survey_responses',
    ConnectSource: 'connect_source',
    RunFirstQuery: 'run_first_query',
    JoinExternalData: 'join_external_data',
    CreateSavedView: 'create_saved_view',
    EnableErrorTracking: 'enable_error_tracking',
    UploadSourceMaps: 'upload_source_maps',
    ViewFirstError: 'view_first_error',
    ResolveFirstError: 'resolve_first_error',
    IngestFirstLlmEvent: 'ingest_first_llm_event',
    ViewFirstTrace: 'view_first_trace',
    TrackCosts: 'track_costs',
    SetUpLlmEvaluation: 'set_up_llm_evaluation',
    RunAiPlayground: 'run_ai_playground',
    EnableRevenueAnalyticsViewset: 'enable_revenue_analytics_viewset',
    ConnectRevenueSource: 'connect_revenue_source',
    SetUpRevenueGoal: 'set_up_revenue_goal',
    EnableLogCapture: 'enable_log_capture',
    ViewFirstLogs: 'view_first_logs',
    CreateFirstWorkflow: 'create_first_workflow',
    SetUpFirstWorkflowChannel: 'set_up_first_workflow_channel',
    ConfigureWorkflowTrigger: 'configure_workflow_trigger',
    AddWorkflowAction: 'add_workflow_action',
    LaunchWorkflow: 'launch_workflow',
    CreateFirstEndpoint: 'create_first_endpoint',
    ConfigureEndpoint: 'configure_endpoint',
    TestEndpoint: 'test_endpoint',
    CreateEarlyAccessFeature: 'create_early_access_feature',
    UpdateFeatureStage: 'update_feature_stage',
    UsePosthogAi: 'use_posthog_ai',
    UsePosthogCode: 'use_posthog_code',
    UsePosthogMcp: 'use_posthog_mcp',
    UsePosthogInSlack: 'use_posthog_in_slack',
} as const

/**
 * * `AED` - AED
 * * `AFN` - AFN
 * * `ALL` - ALL
 * * `AMD` - AMD
 * * `ANG` - ANG
 * * `AOA` - AOA
 * * `ARS` - ARS
 * * `AUD` - AUD
 * * `AWG` - AWG
 * * `AZN` - AZN
 * * `BAM` - BAM
 * * `BBD` - BBD
 * * `BDT` - BDT
 * * `BGN` - BGN
 * * `BHD` - BHD
 * * `BIF` - BIF
 * * `BMD` - BMD
 * * `BND` - BND
 * * `BOB` - BOB
 * * `BRL` - BRL
 * * `BSD` - BSD
 * * `BTC` - BTC
 * * `BTN` - BTN
 * * `BWP` - BWP
 * * `BYN` - BYN
 * * `BZD` - BZD
 * * `CAD` - CAD
 * * `CDF` - CDF
 * * `CHF` - CHF
 * * `CLP` - CLP
 * * `CNY` - CNY
 * * `COP` - COP
 * * `CRC` - CRC
 * * `CVE` - CVE
 * * `CZK` - CZK
 * * `DJF` - DJF
 * * `DKK` - DKK
 * * `DOP` - DOP
 * * `DZD` - DZD
 * * `EGP` - EGP
 * * `ERN` - ERN
 * * `ETB` - ETB
 * * `EUR` - EUR
 * * `FJD` - FJD
 * * `GBP` - GBP
 * * `GEL` - GEL
 * * `GHS` - GHS
 * * `GIP` - GIP
 * * `GMD` - GMD
 * * `GNF` - GNF
 * * `GTQ` - GTQ
 * * `GYD` - GYD
 * * `HKD` - HKD
 * * `HNL` - HNL
 * * `HRK` - HRK
 * * `HTG` - HTG
 * * `HUF` - HUF
 * * `IDR` - IDR
 * * `ILS` - ILS
 * * `INR` - INR
 * * `IQD` - IQD
 * * `IRR` - IRR
 * * `ISK` - ISK
 * * `JMD` - JMD
 * * `JOD` - JOD
 * * `JPY` - JPY
 * * `KES` - KES
 * * `KGS` - KGS
 * * `KHR` - KHR
 * * `KMF` - KMF
 * * `KRW` - KRW
 * * `KWD` - KWD
 * * `KYD` - KYD
 * * `KZT` - KZT
 * * `LAK` - LAK
 * * `LBP` - LBP
 * * `LKR` - LKR
 * * `LRD` - LRD
 * * `LTL` - LTL
 * * `LVL` - LVL
 * * `LSL` - LSL
 * * `LYD` - LYD
 * * `MAD` - MAD
 * * `MDL` - MDL
 * * `MGA` - MGA
 * * `MKD` - MKD
 * * `MMK` - MMK
 * * `MNT` - MNT
 * * `MOP` - MOP
 * * `MRU` - MRU
 * * `MTL` - MTL
 * * `MUR` - MUR
 * * `MVR` - MVR
 * * `MWK` - MWK
 * * `MXN` - MXN
 * * `MYR` - MYR
 * * `MZN` - MZN
 * * `NAD` - NAD
 * * `NGN` - NGN
 * * `NIO` - NIO
 * * `NOK` - NOK
 * * `NPR` - NPR
 * * `NZD` - NZD
 * * `OMR` - OMR
 * * `PAB` - PAB
 * * `PEN` - PEN
 * * `PGK` - PGK
 * * `PHP` - PHP
 * * `PKR` - PKR
 * * `PLN` - PLN
 * * `PYG` - PYG
 * * `QAR` - QAR
 * * `RON` - RON
 * * `RSD` - RSD
 * * `RUB` - RUB
 * * `RWF` - RWF
 * * `SAR` - SAR
 * * `SBD` - SBD
 * * `SCR` - SCR
 * * `SDG` - SDG
 * * `SEK` - SEK
 * * `SGD` - SGD
 * * `SRD` - SRD
 * * `SSP` - SSP
 * * `STN` - STN
 * * `SYP` - SYP
 * * `SZL` - SZL
 * * `THB` - THB
 * * `TJS` - TJS
 * * `TMT` - TMT
 * * `TND` - TND
 * * `TOP` - TOP
 * * `TRY` - TRY
 * * `TTD` - TTD
 * * `TWD` - TWD
 * * `TZS` - TZS
 * * `UAH` - UAH
 * * `UGX` - UGX
 * * `USD` - USD
 * * `UYU` - UYU
 * * `UZS` - UZS
 * * `VES` - VES
 * * `VND` - VND
 * * `VUV` - VUV
 * * `WST` - WST
 * * `XAF` - XAF
 * * `XCD` - XCD
 * * `XOF` - XOF
 * * `XPF` - XPF
 * * `YER` - YER
 * * `ZAR` - ZAR
 * * `ZMW` - ZMW
 */
export type BaseCurrencyEnumApi = (typeof BaseCurrencyEnumApi)[keyof typeof BaseCurrencyEnumApi]

export const BaseCurrencyEnumApi = {
    Aed: 'AED',
    Afn: 'AFN',
    All: 'ALL',
    Amd: 'AMD',
    Ang: 'ANG',
    Aoa: 'AOA',
    Ars: 'ARS',
    Aud: 'AUD',
    Awg: 'AWG',
    Azn: 'AZN',
    Bam: 'BAM',
    Bbd: 'BBD',
    Bdt: 'BDT',
    Bgn: 'BGN',
    Bhd: 'BHD',
    Bif: 'BIF',
    Bmd: 'BMD',
    Bnd: 'BND',
    Bob: 'BOB',
    Brl: 'BRL',
    Bsd: 'BSD',
    Btc: 'BTC',
    Btn: 'BTN',
    Bwp: 'BWP',
    Byn: 'BYN',
    Bzd: 'BZD',
    Cad: 'CAD',
    Cdf: 'CDF',
    Chf: 'CHF',
    Clp: 'CLP',
    Cny: 'CNY',
    Cop: 'COP',
    Crc: 'CRC',
    Cve: 'CVE',
    Czk: 'CZK',
    Djf: 'DJF',
    Dkk: 'DKK',
    Dop: 'DOP',
    Dzd: 'DZD',
    Egp: 'EGP',
    Ern: 'ERN',
    Etb: 'ETB',
    Eur: 'EUR',
    Fjd: 'FJD',
    Gbp: 'GBP',
    Gel: 'GEL',
    Ghs: 'GHS',
    Gip: 'GIP',
    Gmd: 'GMD',
    Gnf: 'GNF',
    Gtq: 'GTQ',
    Gyd: 'GYD',
    Hkd: 'HKD',
    Hnl: 'HNL',
    Hrk: 'HRK',
    Htg: 'HTG',
    Huf: 'HUF',
    Idr: 'IDR',
    Ils: 'ILS',
    Inr: 'INR',
    Iqd: 'IQD',
    Irr: 'IRR',
    Isk: 'ISK',
    Jmd: 'JMD',
    Jod: 'JOD',
    Jpy: 'JPY',
    Kes: 'KES',
    Kgs: 'KGS',
    Khr: 'KHR',
    Kmf: 'KMF',
    Krw: 'KRW',
    Kwd: 'KWD',
    Kyd: 'KYD',
    Kzt: 'KZT',
    Lak: 'LAK',
    Lbp: 'LBP',
    Lkr: 'LKR',
    Lrd: 'LRD',
    Ltl: 'LTL',
    Lvl: 'LVL',
    Lsl: 'LSL',
    Lyd: 'LYD',
    Mad: 'MAD',
    Mdl: 'MDL',
    Mga: 'MGA',
    Mkd: 'MKD',
    Mmk: 'MMK',
    Mnt: 'MNT',
    Mop: 'MOP',
    Mru: 'MRU',
    Mtl: 'MTL',
    Mur: 'MUR',
    Mvr: 'MVR',
    Mwk: 'MWK',
    Mxn: 'MXN',
    Myr: 'MYR',
    Mzn: 'MZN',
    Nad: 'NAD',
    Ngn: 'NGN',
    Nio: 'NIO',
    Nok: 'NOK',
    Npr: 'NPR',
    Nzd: 'NZD',
    Omr: 'OMR',
    Pab: 'PAB',
    Pen: 'PEN',
    Pgk: 'PGK',
    Php: 'PHP',
    Pkr: 'PKR',
    Pln: 'PLN',
    Pyg: 'PYG',
    Qar: 'QAR',
    Ron: 'RON',
    Rsd: 'RSD',
    Rub: 'RUB',
    Rwf: 'RWF',
    Sar: 'SAR',
    Sbd: 'SBD',
    Scr: 'SCR',
    Sdg: 'SDG',
    Sek: 'SEK',
    Sgd: 'SGD',
    Srd: 'SRD',
    Ssp: 'SSP',
    Stn: 'STN',
    Syp: 'SYP',
    Szl: 'SZL',
    Thb: 'THB',
    Tjs: 'TJS',
    Tmt: 'TMT',
    Tnd: 'TND',
    Top: 'TOP',
    Try: 'TRY',
    Ttd: 'TTD',
    Twd: 'TWD',
    Tzs: 'TZS',
    Uah: 'UAH',
    Ugx: 'UGX',
    Usd: 'USD',
    Uyu: 'UYU',
    Uzs: 'UZS',
    Ves: 'VES',
    Vnd: 'VND',
    Vuv: 'VUV',
    Wst: 'WST',
    Xaf: 'XAF',
    Xcd: 'XCD',
    Xof: 'XOF',
    Xpf: 'XPF',
    Yer: 'YER',
    Zar: 'ZAR',
    Zmw: 'ZMW',
} as const

export interface TeamRevenueAnalyticsConfigApi {
    base_currency?: BaseCurrencyEnumApi
    events?: unknown
    goals?: unknown
    filter_test_accounts?: boolean
}

/**
 * * `first_touch` - First Touch
 * * `last_touch` - Last Touch
 * * `linear` - Linear
 * * `time_decay` - Time Decay
 * * `position_based` - Position Based
 */
export type AttributionModeEnumApi = (typeof AttributionModeEnumApi)[keyof typeof AttributionModeEnumApi]

export const AttributionModeEnumApi = {
    FirstTouch: 'first_touch',
    LastTouch: 'last_touch',
    Linear: 'linear',
    TimeDecay: 'time_decay',
    PositionBased: 'position_based',
} as const

export interface TeamMarketingAnalyticsConfigApi {
    sources_map?: unknown
    conversion_goals?: unknown
    /**
     * @minimum 1
     * @maximum 90
     */
    attribution_window_days?: number
    attribution_mode?: AttributionModeEnumApi
    campaign_name_mappings?: unknown
    custom_source_mappings?: unknown
    campaign_field_preferences?: unknown
}

export interface TeamCustomerAnalyticsConfigApi {
    /** Event used as the activity signal (DAU/WAU/MAU). */
    activity_event?: unknown
    /** Event used to count signup pageviews on dashboards. */
    signup_pageview_event?: unknown
    /** Event used to count signups on dashboards. */
    signup_event?: unknown
    /** Event used to count subscriptions on dashboards. */
    subscription_event?: unknown
    /** Event used to count payments on dashboards. */
    payment_event?: unknown
    /**
     * Index of the group type to treat as an Account in customer analytics. Must reference an existing group type configured for the project.
     * @nullable
     */
    account_group_type_index?: number | null
}

export interface TeamWorkflowsConfigApi {
    /** When enabled, workflows engagement activity (email sends, opens, clicks, bounces, spam reports, unsubscribes) is captured as standard PostHog events ($workflows_email_*) alongside the existing workflow metrics. */
    capture_workflows_engagement_events?: boolean
}

/**
 * * `0` - Disabled
 * * `1` - Stateless
 * * `2` - Stateful
 */
export type CookielessServerHashModeEnumApi =
    (typeof CookielessServerHashModeEnumApi)[keyof typeof CookielessServerHashModeEnumApi]

export const CookielessServerHashModeEnumApi = {
    Number0: 0,
    Number1: 1,
    Number2: 2,
} as const

/**
 * Mixin for serializers to add user access control fields
 */
export interface ProjectBackwardCompatApi {
    readonly id: number
    readonly organization: string
    /**
     * Human-readable project name.
     * @minLength 1
     * @maxLength 200
     */
    name?: string
    /**
     * Short description of what the project is about. This is helpful to give our AI agents context about your project.
     * @maxLength 1000
     * @nullable
     */
    product_description?: string | null
    readonly created_at: string
    readonly effective_membership_level: EffectiveMembershipLevelEnumApi
    readonly has_group_types: boolean
    readonly group_types: readonly ProjectBackwardCompatApiGroupTypesItem[]
    /** @nullable */
    readonly live_events_token: string | null
    /** @nullable */
    readonly updated_at: string | null
    readonly uuid: string
    readonly api_token: string
    /** @items.maxLength 200 */
    app_urls?: (string | null)[]
    /** When true, PostHog drops the IP address from every ingested event. */
    anonymize_ips?: boolean
    completed_snippet_onboarding?: boolean
    readonly ingested_event: boolean
    /** Filter groups that identify internal/test traffic to be excluded from insights. */
    test_account_filters?: unknown
    /**
     * When true, new insights default to excluding internal/test users.
     * @nullable
     */
    test_account_filters_default_checked?: boolean | null
    /** Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths. */
    path_cleaning_filters?: unknown
    is_demo?: boolean
    /** IANA timezone used for date-based filters and reporting (e.g. `America/Los_Angeles`).
     *
     * * `Africa/Abidjan` - Africa/Abidjan
     * * `Africa/Accra` - Africa/Accra
     * * `Africa/Addis_Ababa` - Africa/Addis_Ababa
     * * `Africa/Algiers` - Africa/Algiers
     * * `Africa/Asmara` - Africa/Asmara
     * * `Africa/Asmera` - Africa/Asmera
     * * `Africa/Bamako` - Africa/Bamako
     * * `Africa/Bangui` - Africa/Bangui
     * * `Africa/Banjul` - Africa/Banjul
     * * `Africa/Bissau` - Africa/Bissau
     * * `Africa/Blantyre` - Africa/Blantyre
     * * `Africa/Brazzaville` - Africa/Brazzaville
     * * `Africa/Bujumbura` - Africa/Bujumbura
     * * `Africa/Cairo` - Africa/Cairo
     * * `Africa/Casablanca` - Africa/Casablanca
     * * `Africa/Ceuta` - Africa/Ceuta
     * * `Africa/Conakry` - Africa/Conakry
     * * `Africa/Dakar` - Africa/Dakar
     * * `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam
     * * `Africa/Djibouti` - Africa/Djibouti
     * * `Africa/Douala` - Africa/Douala
     * * `Africa/El_Aaiun` - Africa/El_Aaiun
     * * `Africa/Freetown` - Africa/Freetown
     * * `Africa/Gaborone` - Africa/Gaborone
     * * `Africa/Harare` - Africa/Harare
     * * `Africa/Johannesburg` - Africa/Johannesburg
     * * `Africa/Juba` - Africa/Juba
     * * `Africa/Kampala` - Africa/Kampala
     * * `Africa/Khartoum` - Africa/Khartoum
     * * `Africa/Kigali` - Africa/Kigali
     * * `Africa/Kinshasa` - Africa/Kinshasa
     * * `Africa/Lagos` - Africa/Lagos
     * * `Africa/Libreville` - Africa/Libreville
     * * `Africa/Lome` - Africa/Lome
     * * `Africa/Luanda` - Africa/Luanda
     * * `Africa/Lubumbashi` - Africa/Lubumbashi
     * * `Africa/Lusaka` - Africa/Lusaka
     * * `Africa/Malabo` - Africa/Malabo
     * * `Africa/Maputo` - Africa/Maputo
     * * `Africa/Maseru` - Africa/Maseru
     * * `Africa/Mbabane` - Africa/Mbabane
     * * `Africa/Mogadishu` - Africa/Mogadishu
     * * `Africa/Monrovia` - Africa/Monrovia
     * * `Africa/Nairobi` - Africa/Nairobi
     * * `Africa/Ndjamena` - Africa/Ndjamena
     * * `Africa/Niamey` - Africa/Niamey
     * * `Africa/Nouakchott` - Africa/Nouakchott
     * * `Africa/Ouagadougou` - Africa/Ouagadougou
     * * `Africa/Porto-Novo` - Africa/Porto-Novo
     * * `Africa/Sao_Tome` - Africa/Sao_Tome
     * * `Africa/Timbuktu` - Africa/Timbuktu
     * * `Africa/Tripoli` - Africa/Tripoli
     * * `Africa/Tunis` - Africa/Tunis
     * * `Africa/Windhoek` - Africa/Windhoek
     * * `America/Adak` - America/Adak
     * * `America/Anchorage` - America/Anchorage
     * * `America/Anguilla` - America/Anguilla
     * * `America/Antigua` - America/Antigua
     * * `America/Araguaina` - America/Araguaina
     * * `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires
     * * `America/Argentina/Catamarca` - America/Argentina/Catamarca
     * * `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia
     * * `America/Argentina/Cordoba` - America/Argentina/Cordoba
     * * `America/Argentina/Jujuy` - America/Argentina/Jujuy
     * * `America/Argentina/La_Rioja` - America/Argentina/La_Rioja
     * * `America/Argentina/Mendoza` - America/Argentina/Mendoza
     * * `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos
     * * `America/Argentina/Salta` - America/Argentina/Salta
     * * `America/Argentina/San_Juan` - America/Argentina/San_Juan
     * * `America/Argentina/San_Luis` - America/Argentina/San_Luis
     * * `America/Argentina/Tucuman` - America/Argentina/Tucuman
     * * `America/Argentina/Ushuaia` - America/Argentina/Ushuaia
     * * `America/Aruba` - America/Aruba
     * * `America/Asuncion` - America/Asuncion
     * * `America/Atikokan` - America/Atikokan
     * * `America/Atka` - America/Atka
     * * `America/Bahia` - America/Bahia
     * * `America/Bahia_Banderas` - America/Bahia_Banderas
     * * `America/Barbados` - America/Barbados
     * * `America/Belem` - America/Belem
     * * `America/Belize` - America/Belize
     * * `America/Blanc-Sablon` - America/Blanc-Sablon
     * * `America/Boa_Vista` - America/Boa_Vista
     * * `America/Bogota` - America/Bogota
     * * `America/Boise` - America/Boise
     * * `America/Buenos_Aires` - America/Buenos_Aires
     * * `America/Cambridge_Bay` - America/Cambridge_Bay
     * * `America/Campo_Grande` - America/Campo_Grande
     * * `America/Cancun` - America/Cancun
     * * `America/Caracas` - America/Caracas
     * * `America/Catamarca` - America/Catamarca
     * * `America/Cayenne` - America/Cayenne
     * * `America/Cayman` - America/Cayman
     * * `America/Chicago` - America/Chicago
     * * `America/Chihuahua` - America/Chihuahua
     * * `America/Ciudad_Juarez` - America/Ciudad_Juarez
     * * `America/Coral_Harbour` - America/Coral_Harbour
     * * `America/Cordoba` - America/Cordoba
     * * `America/Costa_Rica` - America/Costa_Rica
     * * `America/Creston` - America/Creston
     * * `America/Cuiaba` - America/Cuiaba
     * * `America/Curacao` - America/Curacao
     * * `America/Danmarkshavn` - America/Danmarkshavn
     * * `America/Dawson` - America/Dawson
     * * `America/Dawson_Creek` - America/Dawson_Creek
     * * `America/Denver` - America/Denver
     * * `America/Detroit` - America/Detroit
     * * `America/Dominica` - America/Dominica
     * * `America/Edmonton` - America/Edmonton
     * * `America/Eirunepe` - America/Eirunepe
     * * `America/El_Salvador` - America/El_Salvador
     * * `America/Ensenada` - America/Ensenada
     * * `America/Fort_Nelson` - America/Fort_Nelson
     * * `America/Fort_Wayne` - America/Fort_Wayne
     * * `America/Fortaleza` - America/Fortaleza
     * * `America/Glace_Bay` - America/Glace_Bay
     * * `America/Godthab` - America/Godthab
     * * `America/Goose_Bay` - America/Goose_Bay
     * * `America/Grand_Turk` - America/Grand_Turk
     * * `America/Grenada` - America/Grenada
     * * `America/Guadeloupe` - America/Guadeloupe
     * * `America/Guatemala` - America/Guatemala
     * * `America/Guayaquil` - America/Guayaquil
     * * `America/Guyana` - America/Guyana
     * * `America/Halifax` - America/Halifax
     * * `America/Havana` - America/Havana
     * * `America/Hermosillo` - America/Hermosillo
     * * `America/Indiana/Indianapolis` - America/Indiana/Indianapolis
     * * `America/Indiana/Knox` - America/Indiana/Knox
     * * `America/Indiana/Marengo` - America/Indiana/Marengo
     * * `America/Indiana/Petersburg` - America/Indiana/Petersburg
     * * `America/Indiana/Tell_City` - America/Indiana/Tell_City
     * * `America/Indiana/Vevay` - America/Indiana/Vevay
     * * `America/Indiana/Vincennes` - America/Indiana/Vincennes
     * * `America/Indiana/Winamac` - America/Indiana/Winamac
     * * `America/Indianapolis` - America/Indianapolis
     * * `America/Inuvik` - America/Inuvik
     * * `America/Iqaluit` - America/Iqaluit
     * * `America/Jamaica` - America/Jamaica
     * * `America/Jujuy` - America/Jujuy
     * * `America/Juneau` - America/Juneau
     * * `America/Kentucky/Louisville` - America/Kentucky/Louisville
     * * `America/Kentucky/Monticello` - America/Kentucky/Monticello
     * * `America/Knox_IN` - America/Knox_IN
     * * `America/Kralendijk` - America/Kralendijk
     * * `America/La_Paz` - America/La_Paz
     * * `America/Lima` - America/Lima
     * * `America/Los_Angeles` - America/Los_Angeles
     * * `America/Louisville` - America/Louisville
     * * `America/Lower_Princes` - America/Lower_Princes
     * * `America/Maceio` - America/Maceio
     * * `America/Managua` - America/Managua
     * * `America/Manaus` - America/Manaus
     * * `America/Marigot` - America/Marigot
     * * `America/Martinique` - America/Martinique
     * * `America/Matamoros` - America/Matamoros
     * * `America/Mazatlan` - America/Mazatlan
     * * `America/Mendoza` - America/Mendoza
     * * `America/Menominee` - America/Menominee
     * * `America/Merida` - America/Merida
     * * `America/Metlakatla` - America/Metlakatla
     * * `America/Mexico_City` - America/Mexico_City
     * * `America/Miquelon` - America/Miquelon
     * * `America/Moncton` - America/Moncton
     * * `America/Monterrey` - America/Monterrey
     * * `America/Montevideo` - America/Montevideo
     * * `America/Montreal` - America/Montreal
     * * `America/Montserrat` - America/Montserrat
     * * `America/Nassau` - America/Nassau
     * * `America/New_York` - America/New_York
     * * `America/Nipigon` - America/Nipigon
     * * `America/Nome` - America/Nome
     * * `America/Noronha` - America/Noronha
     * * `America/North_Dakota/Beulah` - America/North_Dakota/Beulah
     * * `America/North_Dakota/Center` - America/North_Dakota/Center
     * * `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem
     * * `America/Nuuk` - America/Nuuk
     * * `America/Ojinaga` - America/Ojinaga
     * * `America/Panama` - America/Panama
     * * `America/Pangnirtung` - America/Pangnirtung
     * * `America/Paramaribo` - America/Paramaribo
     * * `America/Phoenix` - America/Phoenix
     * * `America/Port-au-Prince` - America/Port-au-Prince
     * * `America/Port_of_Spain` - America/Port_of_Spain
     * * `America/Porto_Acre` - America/Porto_Acre
     * * `America/Porto_Velho` - America/Porto_Velho
     * * `America/Puerto_Rico` - America/Puerto_Rico
     * * `America/Punta_Arenas` - America/Punta_Arenas
     * * `America/Rainy_River` - America/Rainy_River
     * * `America/Rankin_Inlet` - America/Rankin_Inlet
     * * `America/Recife` - America/Recife
     * * `America/Regina` - America/Regina
     * * `America/Resolute` - America/Resolute
     * * `America/Rio_Branco` - America/Rio_Branco
     * * `America/Rosario` - America/Rosario
     * * `America/Santa_Isabel` - America/Santa_Isabel
     * * `America/Santarem` - America/Santarem
     * * `America/Santiago` - America/Santiago
     * * `America/Santo_Domingo` - America/Santo_Domingo
     * * `America/Sao_Paulo` - America/Sao_Paulo
     * * `America/Scoresbysund` - America/Scoresbysund
     * * `America/Shiprock` - America/Shiprock
     * * `America/Sitka` - America/Sitka
     * * `America/St_Barthelemy` - America/St_Barthelemy
     * * `America/St_Johns` - America/St_Johns
     * * `America/St_Kitts` - America/St_Kitts
     * * `America/St_Lucia` - America/St_Lucia
     * * `America/St_Thomas` - America/St_Thomas
     * * `America/St_Vincent` - America/St_Vincent
     * * `America/Swift_Current` - America/Swift_Current
     * * `America/Tegucigalpa` - America/Tegucigalpa
     * * `America/Thule` - America/Thule
     * * `America/Thunder_Bay` - America/Thunder_Bay
     * * `America/Tijuana` - America/Tijuana
     * * `America/Toronto` - America/Toronto
     * * `America/Tortola` - America/Tortola
     * * `America/Vancouver` - America/Vancouver
     * * `America/Virgin` - America/Virgin
     * * `America/Whitehorse` - America/Whitehorse
     * * `America/Winnipeg` - America/Winnipeg
     * * `America/Yakutat` - America/Yakutat
     * * `America/Yellowknife` - America/Yellowknife
     * * `Antarctica/Casey` - Antarctica/Casey
     * * `Antarctica/Davis` - Antarctica/Davis
     * * `Antarctica/DumontDUrville` - Antarctica/DumontDUrville
     * * `Antarctica/Macquarie` - Antarctica/Macquarie
     * * `Antarctica/Mawson` - Antarctica/Mawson
     * * `Antarctica/McMurdo` - Antarctica/McMurdo
     * * `Antarctica/Palmer` - Antarctica/Palmer
     * * `Antarctica/Rothera` - Antarctica/Rothera
     * * `Antarctica/South_Pole` - Antarctica/South_Pole
     * * `Antarctica/Syowa` - Antarctica/Syowa
     * * `Antarctica/Troll` - Antarctica/Troll
     * * `Antarctica/Vostok` - Antarctica/Vostok
     * * `Arctic/Longyearbyen` - Arctic/Longyearbyen
     * * `Asia/Aden` - Asia/Aden
     * * `Asia/Almaty` - Asia/Almaty
     * * `Asia/Amman` - Asia/Amman
     * * `Asia/Anadyr` - Asia/Anadyr
     * * `Asia/Aqtau` - Asia/Aqtau
     * * `Asia/Aqtobe` - Asia/Aqtobe
     * * `Asia/Ashgabat` - Asia/Ashgabat
     * * `Asia/Ashkhabad` - Asia/Ashkhabad
     * * `Asia/Atyrau` - Asia/Atyrau
     * * `Asia/Baghdad` - Asia/Baghdad
     * * `Asia/Bahrain` - Asia/Bahrain
     * * `Asia/Baku` - Asia/Baku
     * * `Asia/Bangkok` - Asia/Bangkok
     * * `Asia/Barnaul` - Asia/Barnaul
     * * `Asia/Beirut` - Asia/Beirut
     * * `Asia/Bishkek` - Asia/Bishkek
     * * `Asia/Brunei` - Asia/Brunei
     * * `Asia/Calcutta` - Asia/Calcutta
     * * `Asia/Chita` - Asia/Chita
     * * `Asia/Choibalsan` - Asia/Choibalsan
     * * `Asia/Chongqing` - Asia/Chongqing
     * * `Asia/Chungking` - Asia/Chungking
     * * `Asia/Colombo` - Asia/Colombo
     * * `Asia/Dacca` - Asia/Dacca
     * * `Asia/Damascus` - Asia/Damascus
     * * `Asia/Dhaka` - Asia/Dhaka
     * * `Asia/Dili` - Asia/Dili
     * * `Asia/Dubai` - Asia/Dubai
     * * `Asia/Dushanbe` - Asia/Dushanbe
     * * `Asia/Famagusta` - Asia/Famagusta
     * * `Asia/Gaza` - Asia/Gaza
     * * `Asia/Harbin` - Asia/Harbin
     * * `Asia/Hebron` - Asia/Hebron
     * * `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh
     * * `Asia/Hong_Kong` - Asia/Hong_Kong
     * * `Asia/Hovd` - Asia/Hovd
     * * `Asia/Irkutsk` - Asia/Irkutsk
     * * `Asia/Istanbul` - Asia/Istanbul
     * * `Asia/Jakarta` - Asia/Jakarta
     * * `Asia/Jayapura` - Asia/Jayapura
     * * `Asia/Jerusalem` - Asia/Jerusalem
     * * `Asia/Kabul` - Asia/Kabul
     * * `Asia/Kamchatka` - Asia/Kamchatka
     * * `Asia/Karachi` - Asia/Karachi
     * * `Asia/Kashgar` - Asia/Kashgar
     * * `Asia/Kathmandu` - Asia/Kathmandu
     * * `Asia/Katmandu` - Asia/Katmandu
     * * `Asia/Khandyga` - Asia/Khandyga
     * * `Asia/Kolkata` - Asia/Kolkata
     * * `Asia/Krasnoyarsk` - Asia/Krasnoyarsk
     * * `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur
     * * `Asia/Kuching` - Asia/Kuching
     * * `Asia/Kuwait` - Asia/Kuwait
     * * `Asia/Macao` - Asia/Macao
     * * `Asia/Macau` - Asia/Macau
     * * `Asia/Magadan` - Asia/Magadan
     * * `Asia/Makassar` - Asia/Makassar
     * * `Asia/Manila` - Asia/Manila
     * * `Asia/Muscat` - Asia/Muscat
     * * `Asia/Nicosia` - Asia/Nicosia
     * * `Asia/Novokuznetsk` - Asia/Novokuznetsk
     * * `Asia/Novosibirsk` - Asia/Novosibirsk
     * * `Asia/Omsk` - Asia/Omsk
     * * `Asia/Oral` - Asia/Oral
     * * `Asia/Phnom_Penh` - Asia/Phnom_Penh
     * * `Asia/Pontianak` - Asia/Pontianak
     * * `Asia/Pyongyang` - Asia/Pyongyang
     * * `Asia/Qatar` - Asia/Qatar
     * * `Asia/Qostanay` - Asia/Qostanay
     * * `Asia/Qyzylorda` - Asia/Qyzylorda
     * * `Asia/Rangoon` - Asia/Rangoon
     * * `Asia/Riyadh` - Asia/Riyadh
     * * `Asia/Saigon` - Asia/Saigon
     * * `Asia/Sakhalin` - Asia/Sakhalin
     * * `Asia/Samarkand` - Asia/Samarkand
     * * `Asia/Seoul` - Asia/Seoul
     * * `Asia/Shanghai` - Asia/Shanghai
     * * `Asia/Singapore` - Asia/Singapore
     * * `Asia/Srednekolymsk` - Asia/Srednekolymsk
     * * `Asia/Taipei` - Asia/Taipei
     * * `Asia/Tashkent` - Asia/Tashkent
     * * `Asia/Tbilisi` - Asia/Tbilisi
     * * `Asia/Tehran` - Asia/Tehran
     * * `Asia/Tel_Aviv` - Asia/Tel_Aviv
     * * `Asia/Thimbu` - Asia/Thimbu
     * * `Asia/Thimphu` - Asia/Thimphu
     * * `Asia/Tokyo` - Asia/Tokyo
     * * `Asia/Tomsk` - Asia/Tomsk
     * * `Asia/Ujung_Pandang` - Asia/Ujung_Pandang
     * * `Asia/Ulaanbaatar` - Asia/Ulaanbaatar
     * * `Asia/Ulan_Bator` - Asia/Ulan_Bator
     * * `Asia/Urumqi` - Asia/Urumqi
     * * `Asia/Ust-Nera` - Asia/Ust-Nera
     * * `Asia/Vientiane` - Asia/Vientiane
     * * `Asia/Vladivostok` - Asia/Vladivostok
     * * `Asia/Yakutsk` - Asia/Yakutsk
     * * `Asia/Yangon` - Asia/Yangon
     * * `Asia/Yekaterinburg` - Asia/Yekaterinburg
     * * `Asia/Yerevan` - Asia/Yerevan
     * * `Atlantic/Azores` - Atlantic/Azores
     * * `Atlantic/Bermuda` - Atlantic/Bermuda
     * * `Atlantic/Canary` - Atlantic/Canary
     * * `Atlantic/Cape_Verde` - Atlantic/Cape_Verde
     * * `Atlantic/Faeroe` - Atlantic/Faeroe
     * * `Atlantic/Faroe` - Atlantic/Faroe
     * * `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen
     * * `Atlantic/Madeira` - Atlantic/Madeira
     * * `Atlantic/Reykjavik` - Atlantic/Reykjavik
     * * `Atlantic/South_Georgia` - Atlantic/South_Georgia
     * * `Atlantic/St_Helena` - Atlantic/St_Helena
     * * `Atlantic/Stanley` - Atlantic/Stanley
     * * `Australia/ACT` - Australia/ACT
     * * `Australia/Adelaide` - Australia/Adelaide
     * * `Australia/Brisbane` - Australia/Brisbane
     * * `Australia/Broken_Hill` - Australia/Broken_Hill
     * * `Australia/Canberra` - Australia/Canberra
     * * `Australia/Currie` - Australia/Currie
     * * `Australia/Darwin` - Australia/Darwin
     * * `Australia/Eucla` - Australia/Eucla
     * * `Australia/Hobart` - Australia/Hobart
     * * `Australia/LHI` - Australia/LHI
     * * `Australia/Lindeman` - Australia/Lindeman
     * * `Australia/Lord_Howe` - Australia/Lord_Howe
     * * `Australia/Melbourne` - Australia/Melbourne
     * * `Australia/NSW` - Australia/NSW
     * * `Australia/North` - Australia/North
     * * `Australia/Perth` - Australia/Perth
     * * `Australia/Queensland` - Australia/Queensland
     * * `Australia/South` - Australia/South
     * * `Australia/Sydney` - Australia/Sydney
     * * `Australia/Tasmania` - Australia/Tasmania
     * * `Australia/Victoria` - Australia/Victoria
     * * `Australia/West` - Australia/West
     * * `Australia/Yancowinna` - Australia/Yancowinna
     * * `Brazil/Acre` - Brazil/Acre
     * * `Brazil/DeNoronha` - Brazil/DeNoronha
     * * `Brazil/East` - Brazil/East
     * * `Brazil/West` - Brazil/West
     * * `CET` - CET
     * * `CST6CDT` - CST6CDT
     * * `Canada/Atlantic` - Canada/Atlantic
     * * `Canada/Central` - Canada/Central
     * * `Canada/Eastern` - Canada/Eastern
     * * `Canada/Mountain` - Canada/Mountain
     * * `Canada/Newfoundland` - Canada/Newfoundland
     * * `Canada/Pacific` - Canada/Pacific
     * * `Canada/Saskatchewan` - Canada/Saskatchewan
     * * `Canada/Yukon` - Canada/Yukon
     * * `Chile/Continental` - Chile/Continental
     * * `Chile/EasterIsland` - Chile/EasterIsland
     * * `Cuba` - Cuba
     * * `EET` - EET
     * * `EST` - EST
     * * `EST5EDT` - EST5EDT
     * * `Egypt` - Egypt
     * * `Eire` - Eire
     * * `Etc/GMT` - Etc/GMT
     * * `Etc/GMT+0` - Etc/GMT+0
     * * `Etc/GMT+1` - Etc/GMT+1
     * * `Etc/GMT+10` - Etc/GMT+10
     * * `Etc/GMT+11` - Etc/GMT+11
     * * `Etc/GMT+12` - Etc/GMT+12
     * * `Etc/GMT+2` - Etc/GMT+2
     * * `Etc/GMT+3` - Etc/GMT+3
     * * `Etc/GMT+4` - Etc/GMT+4
     * * `Etc/GMT+5` - Etc/GMT+5
     * * `Etc/GMT+6` - Etc/GMT+6
     * * `Etc/GMT+7` - Etc/GMT+7
     * * `Etc/GMT+8` - Etc/GMT+8
     * * `Etc/GMT+9` - Etc/GMT+9
     * * `Etc/GMT-0` - Etc/GMT-0
     * * `Etc/GMT-1` - Etc/GMT-1
     * * `Etc/GMT-10` - Etc/GMT-10
     * * `Etc/GMT-11` - Etc/GMT-11
     * * `Etc/GMT-12` - Etc/GMT-12
     * * `Etc/GMT-13` - Etc/GMT-13
     * * `Etc/GMT-14` - Etc/GMT-14
     * * `Etc/GMT-2` - Etc/GMT-2
     * * `Etc/GMT-3` - Etc/GMT-3
     * * `Etc/GMT-4` - Etc/GMT-4
     * * `Etc/GMT-5` - Etc/GMT-5
     * * `Etc/GMT-6` - Etc/GMT-6
     * * `Etc/GMT-7` - Etc/GMT-7
     * * `Etc/GMT-8` - Etc/GMT-8
     * * `Etc/GMT-9` - Etc/GMT-9
     * * `Etc/GMT0` - Etc/GMT0
     * * `Etc/Greenwich` - Etc/Greenwich
     * * `Etc/UCT` - Etc/UCT
     * * `Etc/UTC` - Etc/UTC
     * * `Etc/Universal` - Etc/Universal
     * * `Etc/Zulu` - Etc/Zulu
     * * `Europe/Amsterdam` - Europe/Amsterdam
     * * `Europe/Andorra` - Europe/Andorra
     * * `Europe/Astrakhan` - Europe/Astrakhan
     * * `Europe/Athens` - Europe/Athens
     * * `Europe/Belfast` - Europe/Belfast
     * * `Europe/Belgrade` - Europe/Belgrade
     * * `Europe/Berlin` - Europe/Berlin
     * * `Europe/Bratislava` - Europe/Bratislava
     * * `Europe/Brussels` - Europe/Brussels
     * * `Europe/Bucharest` - Europe/Bucharest
     * * `Europe/Budapest` - Europe/Budapest
     * * `Europe/Busingen` - Europe/Busingen
     * * `Europe/Chisinau` - Europe/Chisinau
     * * `Europe/Copenhagen` - Europe/Copenhagen
     * * `Europe/Dublin` - Europe/Dublin
     * * `Europe/Gibraltar` - Europe/Gibraltar
     * * `Europe/Guernsey` - Europe/Guernsey
     * * `Europe/Helsinki` - Europe/Helsinki
     * * `Europe/Isle_of_Man` - Europe/Isle_of_Man
     * * `Europe/Istanbul` - Europe/Istanbul
     * * `Europe/Jersey` - Europe/Jersey
     * * `Europe/Kaliningrad` - Europe/Kaliningrad
     * * `Europe/Kiev` - Europe/Kiev
     * * `Europe/Kirov` - Europe/Kirov
     * * `Europe/Kyiv` - Europe/Kyiv
     * * `Europe/Lisbon` - Europe/Lisbon
     * * `Europe/Ljubljana` - Europe/Ljubljana
     * * `Europe/London` - Europe/London
     * * `Europe/Luxembourg` - Europe/Luxembourg
     * * `Europe/Madrid` - Europe/Madrid
     * * `Europe/Malta` - Europe/Malta
     * * `Europe/Mariehamn` - Europe/Mariehamn
     * * `Europe/Minsk` - Europe/Minsk
     * * `Europe/Monaco` - Europe/Monaco
     * * `Europe/Moscow` - Europe/Moscow
     * * `Europe/Nicosia` - Europe/Nicosia
     * * `Europe/Oslo` - Europe/Oslo
     * * `Europe/Paris` - Europe/Paris
     * * `Europe/Podgorica` - Europe/Podgorica
     * * `Europe/Prague` - Europe/Prague
     * * `Europe/Riga` - Europe/Riga
     * * `Europe/Rome` - Europe/Rome
     * * `Europe/Samara` - Europe/Samara
     * * `Europe/San_Marino` - Europe/San_Marino
     * * `Europe/Sarajevo` - Europe/Sarajevo
     * * `Europe/Saratov` - Europe/Saratov
     * * `Europe/Simferopol` - Europe/Simferopol
     * * `Europe/Skopje` - Europe/Skopje
     * * `Europe/Sofia` - Europe/Sofia
     * * `Europe/Stockholm` - Europe/Stockholm
     * * `Europe/Tallinn` - Europe/Tallinn
     * * `Europe/Tirane` - Europe/Tirane
     * * `Europe/Tiraspol` - Europe/Tiraspol
     * * `Europe/Ulyanovsk` - Europe/Ulyanovsk
     * * `Europe/Uzhgorod` - Europe/Uzhgorod
     * * `Europe/Vaduz` - Europe/Vaduz
     * * `Europe/Vatican` - Europe/Vatican
     * * `Europe/Vienna` - Europe/Vienna
     * * `Europe/Vilnius` - Europe/Vilnius
     * * `Europe/Volgograd` - Europe/Volgograd
     * * `Europe/Warsaw` - Europe/Warsaw
     * * `Europe/Zagreb` - Europe/Zagreb
     * * `Europe/Zaporozhye` - Europe/Zaporozhye
     * * `Europe/Zurich` - Europe/Zurich
     * * `GB` - GB
     * * `GB-Eire` - GB-Eire
     * * `GMT` - GMT
     * * `GMT+0` - GMT+0
     * * `GMT-0` - GMT-0
     * * `GMT0` - GMT0
     * * `Greenwich` - Greenwich
     * * `HST` - HST
     * * `Hongkong` - Hongkong
     * * `Iceland` - Iceland
     * * `Indian/Antananarivo` - Indian/Antananarivo
     * * `Indian/Chagos` - Indian/Chagos
     * * `Indian/Christmas` - Indian/Christmas
     * * `Indian/Cocos` - Indian/Cocos
     * * `Indian/Comoro` - Indian/Comoro
     * * `Indian/Kerguelen` - Indian/Kerguelen
     * * `Indian/Mahe` - Indian/Mahe
     * * `Indian/Maldives` - Indian/Maldives
     * * `Indian/Mauritius` - Indian/Mauritius
     * * `Indian/Mayotte` - Indian/Mayotte
     * * `Indian/Reunion` - Indian/Reunion
     * * `Iran` - Iran
     * * `Israel` - Israel
     * * `Jamaica` - Jamaica
     * * `Japan` - Japan
     * * `Kwajalein` - Kwajalein
     * * `Libya` - Libya
     * * `MET` - MET
     * * `MST` - MST
     * * `MST7MDT` - MST7MDT
     * * `Mexico/BajaNorte` - Mexico/BajaNorte
     * * `Mexico/BajaSur` - Mexico/BajaSur
     * * `Mexico/General` - Mexico/General
     * * `NZ` - NZ
     * * `NZ-CHAT` - NZ-CHAT
     * * `Navajo` - Navajo
     * * `PRC` - PRC
     * * `PST8PDT` - PST8PDT
     * * `Pacific/Apia` - Pacific/Apia
     * * `Pacific/Auckland` - Pacific/Auckland
     * * `Pacific/Bougainville` - Pacific/Bougainville
     * * `Pacific/Chatham` - Pacific/Chatham
     * * `Pacific/Chuuk` - Pacific/Chuuk
     * * `Pacific/Easter` - Pacific/Easter
     * * `Pacific/Efate` - Pacific/Efate
     * * `Pacific/Enderbury` - Pacific/Enderbury
     * * `Pacific/Fakaofo` - Pacific/Fakaofo
     * * `Pacific/Fiji` - Pacific/Fiji
     * * `Pacific/Funafuti` - Pacific/Funafuti
     * * `Pacific/Galapagos` - Pacific/Galapagos
     * * `Pacific/Gambier` - Pacific/Gambier
     * * `Pacific/Guadalcanal` - Pacific/Guadalcanal
     * * `Pacific/Guam` - Pacific/Guam
     * * `Pacific/Honolulu` - Pacific/Honolulu
     * * `Pacific/Johnston` - Pacific/Johnston
     * * `Pacific/Kanton` - Pacific/Kanton
     * * `Pacific/Kiritimati` - Pacific/Kiritimati
     * * `Pacific/Kosrae` - Pacific/Kosrae
     * * `Pacific/Kwajalein` - Pacific/Kwajalein
     * * `Pacific/Majuro` - Pacific/Majuro
     * * `Pacific/Marquesas` - Pacific/Marquesas
     * * `Pacific/Midway` - Pacific/Midway
     * * `Pacific/Nauru` - Pacific/Nauru
     * * `Pacific/Niue` - Pacific/Niue
     * * `Pacific/Norfolk` - Pacific/Norfolk
     * * `Pacific/Noumea` - Pacific/Noumea
     * * `Pacific/Pago_Pago` - Pacific/Pago_Pago
     * * `Pacific/Palau` - Pacific/Palau
     * * `Pacific/Pitcairn` - Pacific/Pitcairn
     * * `Pacific/Pohnpei` - Pacific/Pohnpei
     * * `Pacific/Ponape` - Pacific/Ponape
     * * `Pacific/Port_Moresby` - Pacific/Port_Moresby
     * * `Pacific/Rarotonga` - Pacific/Rarotonga
     * * `Pacific/Saipan` - Pacific/Saipan
     * * `Pacific/Samoa` - Pacific/Samoa
     * * `Pacific/Tahiti` - Pacific/Tahiti
     * * `Pacific/Tarawa` - Pacific/Tarawa
     * * `Pacific/Tongatapu` - Pacific/Tongatapu
     * * `Pacific/Truk` - Pacific/Truk
     * * `Pacific/Wake` - Pacific/Wake
     * * `Pacific/Wallis` - Pacific/Wallis
     * * `Pacific/Yap` - Pacific/Yap
     * * `Poland` - Poland
     * * `Portugal` - Portugal
     * * `ROC` - ROC
     * * `ROK` - ROK
     * * `Singapore` - Singapore
     * * `Turkey` - Turkey
     * * `UCT` - UCT
     * * `US/Alaska` - US/Alaska
     * * `US/Aleutian` - US/Aleutian
     * * `US/Arizona` - US/Arizona
     * * `US/Central` - US/Central
     * * `US/East-Indiana` - US/East-Indiana
     * * `US/Eastern` - US/Eastern
     * * `US/Hawaii` - US/Hawaii
     * * `US/Indiana-Starke` - US/Indiana-Starke
     * * `US/Michigan` - US/Michigan
     * * `US/Mountain` - US/Mountain
     * * `US/Pacific` - US/Pacific
     * * `US/Samoa` - US/Samoa
     * * `UTC` - UTC
     * * `Universal` - Universal
     * * `W-SU` - W-SU
     * * `WET` - WET
     * * `Zulu` - Zulu */
    timezone?: string
    /** Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`). */
    data_attributes?: unknown
    /**
     * Ordered list of person properties used to render a human-friendly display name in the UI.
     * @nullable
     * @items.maxLength 400
     */
    person_display_name_properties?: string[] | null
    correlation_config?: unknown
    /**
     * Disables posthog-js autocapture (clicks, page views) when true.
     * @nullable
     */
    autocapture_opt_out?: boolean | null
    /**
     * Enables automatic capture of JavaScript exceptions via the SDK.
     * @nullable
     */
    autocapture_exceptions_opt_in?: boolean | null
    /**
     * Enables automatic capture of Core Web Vitals performance metrics.
     * @nullable
     */
    autocapture_web_vitals_opt_in?: boolean | null
    autocapture_web_vitals_allowed_metrics?: unknown
    autocapture_exceptions_errors_to_ignore?: unknown
    /**
     * Enables capturing browser console logs alongside session replays.
     * @nullable
     */
    capture_console_log_opt_in?: boolean | null
    /**
     * Enables capturing performance timing and network requests.
     * @nullable
     */
    capture_performance_opt_in?: boolean | null
    /** Enables session replay recording for this project. */
    session_recording_opt_in?: boolean
    /**
     * Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).
     * @nullable
     * @pattern ^-?\d{0,1}(?:\.\d{0,2})?$
     */
    session_recording_sample_rate?: string | null
    /**
     * Skip saving sessions shorter than this many milliseconds.
     * @minimum 0
     * @maximum 30000
     * @nullable
     */
    session_recording_minimum_duration_milliseconds?: number | null
    session_recording_linked_flag?: unknown
    session_recording_network_payload_capture_config?: unknown
    session_recording_masking_config?: unknown
    /** @nullable */
    session_recording_url_trigger_config?: unknown[] | null
    /** @nullable */
    session_recording_url_blocklist_config?: unknown[] | null
    /** @nullable */
    session_recording_event_trigger_config?: (string | null)[] | null
    /**
     * @maxLength 24
     * @nullable
     */
    session_recording_trigger_match_type_config?: string | null
    /** V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields. */
    session_recording_trigger_groups?: unknown
    /** How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).
     *
     * * `30d` - 30 Days
     * * `90d` - 90 Days
     * * `1y` - 1 Year
     * * `5y` - 5 Years */
    session_recording_retention_period?: SessionRecordingRetentionPeriodEnumApi
    session_replay_config?: unknown
    survey_config?: unknown
    access_control?: boolean
    /** First day of the week for date range filters. 0 = Sunday, 1 = Monday.
     *
     * * `0` - Sunday
     * * `1` - Monday */
    week_start_day?: WeekStartDayEnumApi | null
    /**
     * ID of the dashboard shown as the project's default landing dashboard.
     * @nullable
     */
    primary_dashboard?: number | null
    /** @nullable */
    live_events_columns?: string[] | null
    /**
     * Origins permitted to record session replays and heatmaps. Empty list allows all origins.
     * @nullable
     * @items.maxLength 200
     */
    recording_domains?: (string | null)[] | null
    readonly person_on_events_querying_enabled: boolean
    /** @nullable */
    inject_web_apps?: boolean | null
    extra_settings?: unknown
    modifiers?: unknown
    readonly default_modifiers: ProjectBackwardCompatApiDefaultModifiers
    has_completed_onboarding_for?: unknown
    /**
     * Enables displaying surveys via posthog-js on allowed origins.
     * @nullable
     */
    surveys_opt_in?: boolean | null
    /**
     * Enables heatmap recording on pages that host posthog-js.
     * @nullable
     */
    heatmaps_opt_in?: boolean | null
    readonly product_intents: readonly ProjectBackwardCompatApiProductIntentsItem[]
    /**
     * Default value for the `persist` option on newly created feature flags.
     * @nullable
     */
    flags_persistence_default?: boolean | null
    /** @nullable */
    readonly secret_api_token: string | null
    /** @nullable */
    readonly secret_api_token_backup: string | null
    /** @nullable */
    receive_org_level_activity_logs?: boolean | null
    /** Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.
     *
     * * `b2b` - B2B
     * * `b2c` - B2C
     * * `other` - Other */
    business_model?: BusinessModelEnumApi | BlankEnumApi | null
    /**
     * Enables the customer conversations / live chat product for this project.
     * @nullable
     */
    conversations_enabled?: boolean | null
    conversations_settings?: unknown
    logs_settings?: unknown
    /** @nullable */
    proactive_tasks_enabled?: boolean | null
    readonly available_setup_task_ids: readonly AvailableSetupTaskIdsEnumApi[]
    /**
     * Set to True when project deletion has been initiated. Blocks UI access to this project until the async task completes.
     * @nullable
     */
    readonly is_pending_deletion: boolean | null
    /** ID of the project this environment belongs to. */
    readonly project_id: number
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
    readonly managed_viewsets: ProjectBackwardCompatApiManagedViewsets
    revenue_analytics_config?: TeamRevenueAnalyticsConfigApi
    marketing_analytics_config?: TeamMarketingAnalyticsConfigApi
    customer_analytics_config?: TeamCustomerAnalyticsConfigApi
    workflows_config?: TeamWorkflowsConfigApi
    base_currency?: BaseCurrencyEnumApi
    /**
     * Enables capturing clicks that had no effect (rage-click detection).
     * @nullable
     */
    capture_dead_clicks?: boolean | null
    cookieless_server_hash_mode?: CookielessServerHashModeEnumApi | null
    /** @nullable */
    human_friendly_comparison_periods?: boolean | null
    /** @nullable */
    feature_flag_confirmation_enabled?: boolean | null
    /** @nullable */
    feature_flag_confirmation_message?: string | null
    /**
     * Whether to automatically apply default evaluation contexts to new feature flags
     * @nullable
     */
    default_evaluation_contexts_enabled?: boolean | null
    /**
     * Whether to require at least one evaluation context tag when creating new feature flags
     * @nullable
     */
    require_evaluation_contexts?: boolean | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    default_data_theme?: number | null
    onboarding_tasks?: unknown
    /** @nullable */
    web_analytics_pre_aggregated_tables_enabled?: boolean | null
    /** The team's events data retention window in months (plan-derived, synced from billing). When retention enforcement is active for the team, queries do not return events older than this many months. */
    readonly event_retention_months: number
    /** Whether events data retention is currently enforced for this team (cohort/flag gated). */
    readonly events_retention_enforced: boolean
}

export type PatchedProjectBackwardCompatApiGroupTypesItem = { [key: string]: unknown }

export type PatchedProjectBackwardCompatApiDefaultModifiers = { [key: string]: unknown }

export type PatchedProjectBackwardCompatApiProductIntentsItem = {
    product_type?: string
    created_at?: string
    /** @nullable */
    onboarding_completed_at?: string | null
    updated_at?: string
}

export type PatchedProjectBackwardCompatApiManagedViewsets = { [key: string]: boolean }

/**
 * Mixin for serializers to add user access control fields
 */
export interface PatchedProjectBackwardCompatApi {
    readonly id?: number
    readonly organization?: string
    /**
     * Human-readable project name.
     * @minLength 1
     * @maxLength 200
     */
    name?: string
    /**
     * Short description of what the project is about. This is helpful to give our AI agents context about your project.
     * @maxLength 1000
     * @nullable
     */
    product_description?: string | null
    readonly created_at?: string
    readonly effective_membership_level?: EffectiveMembershipLevelEnumApi
    readonly has_group_types?: boolean
    readonly group_types?: readonly PatchedProjectBackwardCompatApiGroupTypesItem[]
    /** @nullable */
    readonly live_events_token?: string | null
    /** @nullable */
    readonly updated_at?: string | null
    readonly uuid?: string
    readonly api_token?: string
    /** @items.maxLength 200 */
    app_urls?: (string | null)[]
    /** When true, PostHog drops the IP address from every ingested event. */
    anonymize_ips?: boolean
    completed_snippet_onboarding?: boolean
    readonly ingested_event?: boolean
    /** Filter groups that identify internal/test traffic to be excluded from insights. */
    test_account_filters?: unknown
    /**
     * When true, new insights default to excluding internal/test users.
     * @nullable
     */
    test_account_filters_default_checked?: boolean | null
    /** Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths. */
    path_cleaning_filters?: unknown
    is_demo?: boolean
    /** IANA timezone used for date-based filters and reporting (e.g. `America/Los_Angeles`).
     *
     * * `Africa/Abidjan` - Africa/Abidjan
     * * `Africa/Accra` - Africa/Accra
     * * `Africa/Addis_Ababa` - Africa/Addis_Ababa
     * * `Africa/Algiers` - Africa/Algiers
     * * `Africa/Asmara` - Africa/Asmara
     * * `Africa/Asmera` - Africa/Asmera
     * * `Africa/Bamako` - Africa/Bamako
     * * `Africa/Bangui` - Africa/Bangui
     * * `Africa/Banjul` - Africa/Banjul
     * * `Africa/Bissau` - Africa/Bissau
     * * `Africa/Blantyre` - Africa/Blantyre
     * * `Africa/Brazzaville` - Africa/Brazzaville
     * * `Africa/Bujumbura` - Africa/Bujumbura
     * * `Africa/Cairo` - Africa/Cairo
     * * `Africa/Casablanca` - Africa/Casablanca
     * * `Africa/Ceuta` - Africa/Ceuta
     * * `Africa/Conakry` - Africa/Conakry
     * * `Africa/Dakar` - Africa/Dakar
     * * `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam
     * * `Africa/Djibouti` - Africa/Djibouti
     * * `Africa/Douala` - Africa/Douala
     * * `Africa/El_Aaiun` - Africa/El_Aaiun
     * * `Africa/Freetown` - Africa/Freetown
     * * `Africa/Gaborone` - Africa/Gaborone
     * * `Africa/Harare` - Africa/Harare
     * * `Africa/Johannesburg` - Africa/Johannesburg
     * * `Africa/Juba` - Africa/Juba
     * * `Africa/Kampala` - Africa/Kampala
     * * `Africa/Khartoum` - Africa/Khartoum
     * * `Africa/Kigali` - Africa/Kigali
     * * `Africa/Kinshasa` - Africa/Kinshasa
     * * `Africa/Lagos` - Africa/Lagos
     * * `Africa/Libreville` - Africa/Libreville
     * * `Africa/Lome` - Africa/Lome
     * * `Africa/Luanda` - Africa/Luanda
     * * `Africa/Lubumbashi` - Africa/Lubumbashi
     * * `Africa/Lusaka` - Africa/Lusaka
     * * `Africa/Malabo` - Africa/Malabo
     * * `Africa/Maputo` - Africa/Maputo
     * * `Africa/Maseru` - Africa/Maseru
     * * `Africa/Mbabane` - Africa/Mbabane
     * * `Africa/Mogadishu` - Africa/Mogadishu
     * * `Africa/Monrovia` - Africa/Monrovia
     * * `Africa/Nairobi` - Africa/Nairobi
     * * `Africa/Ndjamena` - Africa/Ndjamena
     * * `Africa/Niamey` - Africa/Niamey
     * * `Africa/Nouakchott` - Africa/Nouakchott
     * * `Africa/Ouagadougou` - Africa/Ouagadougou
     * * `Africa/Porto-Novo` - Africa/Porto-Novo
     * * `Africa/Sao_Tome` - Africa/Sao_Tome
     * * `Africa/Timbuktu` - Africa/Timbuktu
     * * `Africa/Tripoli` - Africa/Tripoli
     * * `Africa/Tunis` - Africa/Tunis
     * * `Africa/Windhoek` - Africa/Windhoek
     * * `America/Adak` - America/Adak
     * * `America/Anchorage` - America/Anchorage
     * * `America/Anguilla` - America/Anguilla
     * * `America/Antigua` - America/Antigua
     * * `America/Araguaina` - America/Araguaina
     * * `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires
     * * `America/Argentina/Catamarca` - America/Argentina/Catamarca
     * * `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia
     * * `America/Argentina/Cordoba` - America/Argentina/Cordoba
     * * `America/Argentina/Jujuy` - America/Argentina/Jujuy
     * * `America/Argentina/La_Rioja` - America/Argentina/La_Rioja
     * * `America/Argentina/Mendoza` - America/Argentina/Mendoza
     * * `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos
     * * `America/Argentina/Salta` - America/Argentina/Salta
     * * `America/Argentina/San_Juan` - America/Argentina/San_Juan
     * * `America/Argentina/San_Luis` - America/Argentina/San_Luis
     * * `America/Argentina/Tucuman` - America/Argentina/Tucuman
     * * `America/Argentina/Ushuaia` - America/Argentina/Ushuaia
     * * `America/Aruba` - America/Aruba
     * * `America/Asuncion` - America/Asuncion
     * * `America/Atikokan` - America/Atikokan
     * * `America/Atka` - America/Atka
     * * `America/Bahia` - America/Bahia
     * * `America/Bahia_Banderas` - America/Bahia_Banderas
     * * `America/Barbados` - America/Barbados
     * * `America/Belem` - America/Belem
     * * `America/Belize` - America/Belize
     * * `America/Blanc-Sablon` - America/Blanc-Sablon
     * * `America/Boa_Vista` - America/Boa_Vista
     * * `America/Bogota` - America/Bogota
     * * `America/Boise` - America/Boise
     * * `America/Buenos_Aires` - America/Buenos_Aires
     * * `America/Cambridge_Bay` - America/Cambridge_Bay
     * * `America/Campo_Grande` - America/Campo_Grande
     * * `America/Cancun` - America/Cancun
     * * `America/Caracas` - America/Caracas
     * * `America/Catamarca` - America/Catamarca
     * * `America/Cayenne` - America/Cayenne
     * * `America/Cayman` - America/Cayman
     * * `America/Chicago` - America/Chicago
     * * `America/Chihuahua` - America/Chihuahua
     * * `America/Ciudad_Juarez` - America/Ciudad_Juarez
     * * `America/Coral_Harbour` - America/Coral_Harbour
     * * `America/Cordoba` - America/Cordoba
     * * `America/Costa_Rica` - America/Costa_Rica
     * * `America/Creston` - America/Creston
     * * `America/Cuiaba` - America/Cuiaba
     * * `America/Curacao` - America/Curacao
     * * `America/Danmarkshavn` - America/Danmarkshavn
     * * `America/Dawson` - America/Dawson
     * * `America/Dawson_Creek` - America/Dawson_Creek
     * * `America/Denver` - America/Denver
     * * `America/Detroit` - America/Detroit
     * * `America/Dominica` - America/Dominica
     * * `America/Edmonton` - America/Edmonton
     * * `America/Eirunepe` - America/Eirunepe
     * * `America/El_Salvador` - America/El_Salvador
     * * `America/Ensenada` - America/Ensenada
     * * `America/Fort_Nelson` - America/Fort_Nelson
     * * `America/Fort_Wayne` - America/Fort_Wayne
     * * `America/Fortaleza` - America/Fortaleza
     * * `America/Glace_Bay` - America/Glace_Bay
     * * `America/Godthab` - America/Godthab
     * * `America/Goose_Bay` - America/Goose_Bay
     * * `America/Grand_Turk` - America/Grand_Turk
     * * `America/Grenada` - America/Grenada
     * * `America/Guadeloupe` - America/Guadeloupe
     * * `America/Guatemala` - America/Guatemala
     * * `America/Guayaquil` - America/Guayaquil
     * * `America/Guyana` - America/Guyana
     * * `America/Halifax` - America/Halifax
     * * `America/Havana` - America/Havana
     * * `America/Hermosillo` - America/Hermosillo
     * * `America/Indiana/Indianapolis` - America/Indiana/Indianapolis
     * * `America/Indiana/Knox` - America/Indiana/Knox
     * * `America/Indiana/Marengo` - America/Indiana/Marengo
     * * `America/Indiana/Petersburg` - America/Indiana/Petersburg
     * * `America/Indiana/Tell_City` - America/Indiana/Tell_City
     * * `America/Indiana/Vevay` - America/Indiana/Vevay
     * * `America/Indiana/Vincennes` - America/Indiana/Vincennes
     * * `America/Indiana/Winamac` - America/Indiana/Winamac
     * * `America/Indianapolis` - America/Indianapolis
     * * `America/Inuvik` - America/Inuvik
     * * `America/Iqaluit` - America/Iqaluit
     * * `America/Jamaica` - America/Jamaica
     * * `America/Jujuy` - America/Jujuy
     * * `America/Juneau` - America/Juneau
     * * `America/Kentucky/Louisville` - America/Kentucky/Louisville
     * * `America/Kentucky/Monticello` - America/Kentucky/Monticello
     * * `America/Knox_IN` - America/Knox_IN
     * * `America/Kralendijk` - America/Kralendijk
     * * `America/La_Paz` - America/La_Paz
     * * `America/Lima` - America/Lima
     * * `America/Los_Angeles` - America/Los_Angeles
     * * `America/Louisville` - America/Louisville
     * * `America/Lower_Princes` - America/Lower_Princes
     * * `America/Maceio` - America/Maceio
     * * `America/Managua` - America/Managua
     * * `America/Manaus` - America/Manaus
     * * `America/Marigot` - America/Marigot
     * * `America/Martinique` - America/Martinique
     * * `America/Matamoros` - America/Matamoros
     * * `America/Mazatlan` - America/Mazatlan
     * * `America/Mendoza` - America/Mendoza
     * * `America/Menominee` - America/Menominee
     * * `America/Merida` - America/Merida
     * * `America/Metlakatla` - America/Metlakatla
     * * `America/Mexico_City` - America/Mexico_City
     * * `America/Miquelon` - America/Miquelon
     * * `America/Moncton` - America/Moncton
     * * `America/Monterrey` - America/Monterrey
     * * `America/Montevideo` - America/Montevideo
     * * `America/Montreal` - America/Montreal
     * * `America/Montserrat` - America/Montserrat
     * * `America/Nassau` - America/Nassau
     * * `America/New_York` - America/New_York
     * * `America/Nipigon` - America/Nipigon
     * * `America/Nome` - America/Nome
     * * `America/Noronha` - America/Noronha
     * * `America/North_Dakota/Beulah` - America/North_Dakota/Beulah
     * * `America/North_Dakota/Center` - America/North_Dakota/Center
     * * `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem
     * * `America/Nuuk` - America/Nuuk
     * * `America/Ojinaga` - America/Ojinaga
     * * `America/Panama` - America/Panama
     * * `America/Pangnirtung` - America/Pangnirtung
     * * `America/Paramaribo` - America/Paramaribo
     * * `America/Phoenix` - America/Phoenix
     * * `America/Port-au-Prince` - America/Port-au-Prince
     * * `America/Port_of_Spain` - America/Port_of_Spain
     * * `America/Porto_Acre` - America/Porto_Acre
     * * `America/Porto_Velho` - America/Porto_Velho
     * * `America/Puerto_Rico` - America/Puerto_Rico
     * * `America/Punta_Arenas` - America/Punta_Arenas
     * * `America/Rainy_River` - America/Rainy_River
     * * `America/Rankin_Inlet` - America/Rankin_Inlet
     * * `America/Recife` - America/Recife
     * * `America/Regina` - America/Regina
     * * `America/Resolute` - America/Resolute
     * * `America/Rio_Branco` - America/Rio_Branco
     * * `America/Rosario` - America/Rosario
     * * `America/Santa_Isabel` - America/Santa_Isabel
     * * `America/Santarem` - America/Santarem
     * * `America/Santiago` - America/Santiago
     * * `America/Santo_Domingo` - America/Santo_Domingo
     * * `America/Sao_Paulo` - America/Sao_Paulo
     * * `America/Scoresbysund` - America/Scoresbysund
     * * `America/Shiprock` - America/Shiprock
     * * `America/Sitka` - America/Sitka
     * * `America/St_Barthelemy` - America/St_Barthelemy
     * * `America/St_Johns` - America/St_Johns
     * * `America/St_Kitts` - America/St_Kitts
     * * `America/St_Lucia` - America/St_Lucia
     * * `America/St_Thomas` - America/St_Thomas
     * * `America/St_Vincent` - America/St_Vincent
     * * `America/Swift_Current` - America/Swift_Current
     * * `America/Tegucigalpa` - America/Tegucigalpa
     * * `America/Thule` - America/Thule
     * * `America/Thunder_Bay` - America/Thunder_Bay
     * * `America/Tijuana` - America/Tijuana
     * * `America/Toronto` - America/Toronto
     * * `America/Tortola` - America/Tortola
     * * `America/Vancouver` - America/Vancouver
     * * `America/Virgin` - America/Virgin
     * * `America/Whitehorse` - America/Whitehorse
     * * `America/Winnipeg` - America/Winnipeg
     * * `America/Yakutat` - America/Yakutat
     * * `America/Yellowknife` - America/Yellowknife
     * * `Antarctica/Casey` - Antarctica/Casey
     * * `Antarctica/Davis` - Antarctica/Davis
     * * `Antarctica/DumontDUrville` - Antarctica/DumontDUrville
     * * `Antarctica/Macquarie` - Antarctica/Macquarie
     * * `Antarctica/Mawson` - Antarctica/Mawson
     * * `Antarctica/McMurdo` - Antarctica/McMurdo
     * * `Antarctica/Palmer` - Antarctica/Palmer
     * * `Antarctica/Rothera` - Antarctica/Rothera
     * * `Antarctica/South_Pole` - Antarctica/South_Pole
     * * `Antarctica/Syowa` - Antarctica/Syowa
     * * `Antarctica/Troll` - Antarctica/Troll
     * * `Antarctica/Vostok` - Antarctica/Vostok
     * * `Arctic/Longyearbyen` - Arctic/Longyearbyen
     * * `Asia/Aden` - Asia/Aden
     * * `Asia/Almaty` - Asia/Almaty
     * * `Asia/Amman` - Asia/Amman
     * * `Asia/Anadyr` - Asia/Anadyr
     * * `Asia/Aqtau` - Asia/Aqtau
     * * `Asia/Aqtobe` - Asia/Aqtobe
     * * `Asia/Ashgabat` - Asia/Ashgabat
     * * `Asia/Ashkhabad` - Asia/Ashkhabad
     * * `Asia/Atyrau` - Asia/Atyrau
     * * `Asia/Baghdad` - Asia/Baghdad
     * * `Asia/Bahrain` - Asia/Bahrain
     * * `Asia/Baku` - Asia/Baku
     * * `Asia/Bangkok` - Asia/Bangkok
     * * `Asia/Barnaul` - Asia/Barnaul
     * * `Asia/Beirut` - Asia/Beirut
     * * `Asia/Bishkek` - Asia/Bishkek
     * * `Asia/Brunei` - Asia/Brunei
     * * `Asia/Calcutta` - Asia/Calcutta
     * * `Asia/Chita` - Asia/Chita
     * * `Asia/Choibalsan` - Asia/Choibalsan
     * * `Asia/Chongqing` - Asia/Chongqing
     * * `Asia/Chungking` - Asia/Chungking
     * * `Asia/Colombo` - Asia/Colombo
     * * `Asia/Dacca` - Asia/Dacca
     * * `Asia/Damascus` - Asia/Damascus
     * * `Asia/Dhaka` - Asia/Dhaka
     * * `Asia/Dili` - Asia/Dili
     * * `Asia/Dubai` - Asia/Dubai
     * * `Asia/Dushanbe` - Asia/Dushanbe
     * * `Asia/Famagusta` - Asia/Famagusta
     * * `Asia/Gaza` - Asia/Gaza
     * * `Asia/Harbin` - Asia/Harbin
     * * `Asia/Hebron` - Asia/Hebron
     * * `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh
     * * `Asia/Hong_Kong` - Asia/Hong_Kong
     * * `Asia/Hovd` - Asia/Hovd
     * * `Asia/Irkutsk` - Asia/Irkutsk
     * * `Asia/Istanbul` - Asia/Istanbul
     * * `Asia/Jakarta` - Asia/Jakarta
     * * `Asia/Jayapura` - Asia/Jayapura
     * * `Asia/Jerusalem` - Asia/Jerusalem
     * * `Asia/Kabul` - Asia/Kabul
     * * `Asia/Kamchatka` - Asia/Kamchatka
     * * `Asia/Karachi` - Asia/Karachi
     * * `Asia/Kashgar` - Asia/Kashgar
     * * `Asia/Kathmandu` - Asia/Kathmandu
     * * `Asia/Katmandu` - Asia/Katmandu
     * * `Asia/Khandyga` - Asia/Khandyga
     * * `Asia/Kolkata` - Asia/Kolkata
     * * `Asia/Krasnoyarsk` - Asia/Krasnoyarsk
     * * `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur
     * * `Asia/Kuching` - Asia/Kuching
     * * `Asia/Kuwait` - Asia/Kuwait
     * * `Asia/Macao` - Asia/Macao
     * * `Asia/Macau` - Asia/Macau
     * * `Asia/Magadan` - Asia/Magadan
     * * `Asia/Makassar` - Asia/Makassar
     * * `Asia/Manila` - Asia/Manila
     * * `Asia/Muscat` - Asia/Muscat
     * * `Asia/Nicosia` - Asia/Nicosia
     * * `Asia/Novokuznetsk` - Asia/Novokuznetsk
     * * `Asia/Novosibirsk` - Asia/Novosibirsk
     * * `Asia/Omsk` - Asia/Omsk
     * * `Asia/Oral` - Asia/Oral
     * * `Asia/Phnom_Penh` - Asia/Phnom_Penh
     * * `Asia/Pontianak` - Asia/Pontianak
     * * `Asia/Pyongyang` - Asia/Pyongyang
     * * `Asia/Qatar` - Asia/Qatar
     * * `Asia/Qostanay` - Asia/Qostanay
     * * `Asia/Qyzylorda` - Asia/Qyzylorda
     * * `Asia/Rangoon` - Asia/Rangoon
     * * `Asia/Riyadh` - Asia/Riyadh
     * * `Asia/Saigon` - Asia/Saigon
     * * `Asia/Sakhalin` - Asia/Sakhalin
     * * `Asia/Samarkand` - Asia/Samarkand
     * * `Asia/Seoul` - Asia/Seoul
     * * `Asia/Shanghai` - Asia/Shanghai
     * * `Asia/Singapore` - Asia/Singapore
     * * `Asia/Srednekolymsk` - Asia/Srednekolymsk
     * * `Asia/Taipei` - Asia/Taipei
     * * `Asia/Tashkent` - Asia/Tashkent
     * * `Asia/Tbilisi` - Asia/Tbilisi
     * * `Asia/Tehran` - Asia/Tehran
     * * `Asia/Tel_Aviv` - Asia/Tel_Aviv
     * * `Asia/Thimbu` - Asia/Thimbu
     * * `Asia/Thimphu` - Asia/Thimphu
     * * `Asia/Tokyo` - Asia/Tokyo
     * * `Asia/Tomsk` - Asia/Tomsk
     * * `Asia/Ujung_Pandang` - Asia/Ujung_Pandang
     * * `Asia/Ulaanbaatar` - Asia/Ulaanbaatar
     * * `Asia/Ulan_Bator` - Asia/Ulan_Bator
     * * `Asia/Urumqi` - Asia/Urumqi
     * * `Asia/Ust-Nera` - Asia/Ust-Nera
     * * `Asia/Vientiane` - Asia/Vientiane
     * * `Asia/Vladivostok` - Asia/Vladivostok
     * * `Asia/Yakutsk` - Asia/Yakutsk
     * * `Asia/Yangon` - Asia/Yangon
     * * `Asia/Yekaterinburg` - Asia/Yekaterinburg
     * * `Asia/Yerevan` - Asia/Yerevan
     * * `Atlantic/Azores` - Atlantic/Azores
     * * `Atlantic/Bermuda` - Atlantic/Bermuda
     * * `Atlantic/Canary` - Atlantic/Canary
     * * `Atlantic/Cape_Verde` - Atlantic/Cape_Verde
     * * `Atlantic/Faeroe` - Atlantic/Faeroe
     * * `Atlantic/Faroe` - Atlantic/Faroe
     * * `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen
     * * `Atlantic/Madeira` - Atlantic/Madeira
     * * `Atlantic/Reykjavik` - Atlantic/Reykjavik
     * * `Atlantic/South_Georgia` - Atlantic/South_Georgia
     * * `Atlantic/St_Helena` - Atlantic/St_Helena
     * * `Atlantic/Stanley` - Atlantic/Stanley
     * * `Australia/ACT` - Australia/ACT
     * * `Australia/Adelaide` - Australia/Adelaide
     * * `Australia/Brisbane` - Australia/Brisbane
     * * `Australia/Broken_Hill` - Australia/Broken_Hill
     * * `Australia/Canberra` - Australia/Canberra
     * * `Australia/Currie` - Australia/Currie
     * * `Australia/Darwin` - Australia/Darwin
     * * `Australia/Eucla` - Australia/Eucla
     * * `Australia/Hobart` - Australia/Hobart
     * * `Australia/LHI` - Australia/LHI
     * * `Australia/Lindeman` - Australia/Lindeman
     * * `Australia/Lord_Howe` - Australia/Lord_Howe
     * * `Australia/Melbourne` - Australia/Melbourne
     * * `Australia/NSW` - Australia/NSW
     * * `Australia/North` - Australia/North
     * * `Australia/Perth` - Australia/Perth
     * * `Australia/Queensland` - Australia/Queensland
     * * `Australia/South` - Australia/South
     * * `Australia/Sydney` - Australia/Sydney
     * * `Australia/Tasmania` - Australia/Tasmania
     * * `Australia/Victoria` - Australia/Victoria
     * * `Australia/West` - Australia/West
     * * `Australia/Yancowinna` - Australia/Yancowinna
     * * `Brazil/Acre` - Brazil/Acre
     * * `Brazil/DeNoronha` - Brazil/DeNoronha
     * * `Brazil/East` - Brazil/East
     * * `Brazil/West` - Brazil/West
     * * `CET` - CET
     * * `CST6CDT` - CST6CDT
     * * `Canada/Atlantic` - Canada/Atlantic
     * * `Canada/Central` - Canada/Central
     * * `Canada/Eastern` - Canada/Eastern
     * * `Canada/Mountain` - Canada/Mountain
     * * `Canada/Newfoundland` - Canada/Newfoundland
     * * `Canada/Pacific` - Canada/Pacific
     * * `Canada/Saskatchewan` - Canada/Saskatchewan
     * * `Canada/Yukon` - Canada/Yukon
     * * `Chile/Continental` - Chile/Continental
     * * `Chile/EasterIsland` - Chile/EasterIsland
     * * `Cuba` - Cuba
     * * `EET` - EET
     * * `EST` - EST
     * * `EST5EDT` - EST5EDT
     * * `Egypt` - Egypt
     * * `Eire` - Eire
     * * `Etc/GMT` - Etc/GMT
     * * `Etc/GMT+0` - Etc/GMT+0
     * * `Etc/GMT+1` - Etc/GMT+1
     * * `Etc/GMT+10` - Etc/GMT+10
     * * `Etc/GMT+11` - Etc/GMT+11
     * * `Etc/GMT+12` - Etc/GMT+12
     * * `Etc/GMT+2` - Etc/GMT+2
     * * `Etc/GMT+3` - Etc/GMT+3
     * * `Etc/GMT+4` - Etc/GMT+4
     * * `Etc/GMT+5` - Etc/GMT+5
     * * `Etc/GMT+6` - Etc/GMT+6
     * * `Etc/GMT+7` - Etc/GMT+7
     * * `Etc/GMT+8` - Etc/GMT+8
     * * `Etc/GMT+9` - Etc/GMT+9
     * * `Etc/GMT-0` - Etc/GMT-0
     * * `Etc/GMT-1` - Etc/GMT-1
     * * `Etc/GMT-10` - Etc/GMT-10
     * * `Etc/GMT-11` - Etc/GMT-11
     * * `Etc/GMT-12` - Etc/GMT-12
     * * `Etc/GMT-13` - Etc/GMT-13
     * * `Etc/GMT-14` - Etc/GMT-14
     * * `Etc/GMT-2` - Etc/GMT-2
     * * `Etc/GMT-3` - Etc/GMT-3
     * * `Etc/GMT-4` - Etc/GMT-4
     * * `Etc/GMT-5` - Etc/GMT-5
     * * `Etc/GMT-6` - Etc/GMT-6
     * * `Etc/GMT-7` - Etc/GMT-7
     * * `Etc/GMT-8` - Etc/GMT-8
     * * `Etc/GMT-9` - Etc/GMT-9
     * * `Etc/GMT0` - Etc/GMT0
     * * `Etc/Greenwich` - Etc/Greenwich
     * * `Etc/UCT` - Etc/UCT
     * * `Etc/UTC` - Etc/UTC
     * * `Etc/Universal` - Etc/Universal
     * * `Etc/Zulu` - Etc/Zulu
     * * `Europe/Amsterdam` - Europe/Amsterdam
     * * `Europe/Andorra` - Europe/Andorra
     * * `Europe/Astrakhan` - Europe/Astrakhan
     * * `Europe/Athens` - Europe/Athens
     * * `Europe/Belfast` - Europe/Belfast
     * * `Europe/Belgrade` - Europe/Belgrade
     * * `Europe/Berlin` - Europe/Berlin
     * * `Europe/Bratislava` - Europe/Bratislava
     * * `Europe/Brussels` - Europe/Brussels
     * * `Europe/Bucharest` - Europe/Bucharest
     * * `Europe/Budapest` - Europe/Budapest
     * * `Europe/Busingen` - Europe/Busingen
     * * `Europe/Chisinau` - Europe/Chisinau
     * * `Europe/Copenhagen` - Europe/Copenhagen
     * * `Europe/Dublin` - Europe/Dublin
     * * `Europe/Gibraltar` - Europe/Gibraltar
     * * `Europe/Guernsey` - Europe/Guernsey
     * * `Europe/Helsinki` - Europe/Helsinki
     * * `Europe/Isle_of_Man` - Europe/Isle_of_Man
     * * `Europe/Istanbul` - Europe/Istanbul
     * * `Europe/Jersey` - Europe/Jersey
     * * `Europe/Kaliningrad` - Europe/Kaliningrad
     * * `Europe/Kiev` - Europe/Kiev
     * * `Europe/Kirov` - Europe/Kirov
     * * `Europe/Kyiv` - Europe/Kyiv
     * * `Europe/Lisbon` - Europe/Lisbon
     * * `Europe/Ljubljana` - Europe/Ljubljana
     * * `Europe/London` - Europe/London
     * * `Europe/Luxembourg` - Europe/Luxembourg
     * * `Europe/Madrid` - Europe/Madrid
     * * `Europe/Malta` - Europe/Malta
     * * `Europe/Mariehamn` - Europe/Mariehamn
     * * `Europe/Minsk` - Europe/Minsk
     * * `Europe/Monaco` - Europe/Monaco
     * * `Europe/Moscow` - Europe/Moscow
     * * `Europe/Nicosia` - Europe/Nicosia
     * * `Europe/Oslo` - Europe/Oslo
     * * `Europe/Paris` - Europe/Paris
     * * `Europe/Podgorica` - Europe/Podgorica
     * * `Europe/Prague` - Europe/Prague
     * * `Europe/Riga` - Europe/Riga
     * * `Europe/Rome` - Europe/Rome
     * * `Europe/Samara` - Europe/Samara
     * * `Europe/San_Marino` - Europe/San_Marino
     * * `Europe/Sarajevo` - Europe/Sarajevo
     * * `Europe/Saratov` - Europe/Saratov
     * * `Europe/Simferopol` - Europe/Simferopol
     * * `Europe/Skopje` - Europe/Skopje
     * * `Europe/Sofia` - Europe/Sofia
     * * `Europe/Stockholm` - Europe/Stockholm
     * * `Europe/Tallinn` - Europe/Tallinn
     * * `Europe/Tirane` - Europe/Tirane
     * * `Europe/Tiraspol` - Europe/Tiraspol
     * * `Europe/Ulyanovsk` - Europe/Ulyanovsk
     * * `Europe/Uzhgorod` - Europe/Uzhgorod
     * * `Europe/Vaduz` - Europe/Vaduz
     * * `Europe/Vatican` - Europe/Vatican
     * * `Europe/Vienna` - Europe/Vienna
     * * `Europe/Vilnius` - Europe/Vilnius
     * * `Europe/Volgograd` - Europe/Volgograd
     * * `Europe/Warsaw` - Europe/Warsaw
     * * `Europe/Zagreb` - Europe/Zagreb
     * * `Europe/Zaporozhye` - Europe/Zaporozhye
     * * `Europe/Zurich` - Europe/Zurich
     * * `GB` - GB
     * * `GB-Eire` - GB-Eire
     * * `GMT` - GMT
     * * `GMT+0` - GMT+0
     * * `GMT-0` - GMT-0
     * * `GMT0` - GMT0
     * * `Greenwich` - Greenwich
     * * `HST` - HST
     * * `Hongkong` - Hongkong
     * * `Iceland` - Iceland
     * * `Indian/Antananarivo` - Indian/Antananarivo
     * * `Indian/Chagos` - Indian/Chagos
     * * `Indian/Christmas` - Indian/Christmas
     * * `Indian/Cocos` - Indian/Cocos
     * * `Indian/Comoro` - Indian/Comoro
     * * `Indian/Kerguelen` - Indian/Kerguelen
     * * `Indian/Mahe` - Indian/Mahe
     * * `Indian/Maldives` - Indian/Maldives
     * * `Indian/Mauritius` - Indian/Mauritius
     * * `Indian/Mayotte` - Indian/Mayotte
     * * `Indian/Reunion` - Indian/Reunion
     * * `Iran` - Iran
     * * `Israel` - Israel
     * * `Jamaica` - Jamaica
     * * `Japan` - Japan
     * * `Kwajalein` - Kwajalein
     * * `Libya` - Libya
     * * `MET` - MET
     * * `MST` - MST
     * * `MST7MDT` - MST7MDT
     * * `Mexico/BajaNorte` - Mexico/BajaNorte
     * * `Mexico/BajaSur` - Mexico/BajaSur
     * * `Mexico/General` - Mexico/General
     * * `NZ` - NZ
     * * `NZ-CHAT` - NZ-CHAT
     * * `Navajo` - Navajo
     * * `PRC` - PRC
     * * `PST8PDT` - PST8PDT
     * * `Pacific/Apia` - Pacific/Apia
     * * `Pacific/Auckland` - Pacific/Auckland
     * * `Pacific/Bougainville` - Pacific/Bougainville
     * * `Pacific/Chatham` - Pacific/Chatham
     * * `Pacific/Chuuk` - Pacific/Chuuk
     * * `Pacific/Easter` - Pacific/Easter
     * * `Pacific/Efate` - Pacific/Efate
     * * `Pacific/Enderbury` - Pacific/Enderbury
     * * `Pacific/Fakaofo` - Pacific/Fakaofo
     * * `Pacific/Fiji` - Pacific/Fiji
     * * `Pacific/Funafuti` - Pacific/Funafuti
     * * `Pacific/Galapagos` - Pacific/Galapagos
     * * `Pacific/Gambier` - Pacific/Gambier
     * * `Pacific/Guadalcanal` - Pacific/Guadalcanal
     * * `Pacific/Guam` - Pacific/Guam
     * * `Pacific/Honolulu` - Pacific/Honolulu
     * * `Pacific/Johnston` - Pacific/Johnston
     * * `Pacific/Kanton` - Pacific/Kanton
     * * `Pacific/Kiritimati` - Pacific/Kiritimati
     * * `Pacific/Kosrae` - Pacific/Kosrae
     * * `Pacific/Kwajalein` - Pacific/Kwajalein
     * * `Pacific/Majuro` - Pacific/Majuro
     * * `Pacific/Marquesas` - Pacific/Marquesas
     * * `Pacific/Midway` - Pacific/Midway
     * * `Pacific/Nauru` - Pacific/Nauru
     * * `Pacific/Niue` - Pacific/Niue
     * * `Pacific/Norfolk` - Pacific/Norfolk
     * * `Pacific/Noumea` - Pacific/Noumea
     * * `Pacific/Pago_Pago` - Pacific/Pago_Pago
     * * `Pacific/Palau` - Pacific/Palau
     * * `Pacific/Pitcairn` - Pacific/Pitcairn
     * * `Pacific/Pohnpei` - Pacific/Pohnpei
     * * `Pacific/Ponape` - Pacific/Ponape
     * * `Pacific/Port_Moresby` - Pacific/Port_Moresby
     * * `Pacific/Rarotonga` - Pacific/Rarotonga
     * * `Pacific/Saipan` - Pacific/Saipan
     * * `Pacific/Samoa` - Pacific/Samoa
     * * `Pacific/Tahiti` - Pacific/Tahiti
     * * `Pacific/Tarawa` - Pacific/Tarawa
     * * `Pacific/Tongatapu` - Pacific/Tongatapu
     * * `Pacific/Truk` - Pacific/Truk
     * * `Pacific/Wake` - Pacific/Wake
     * * `Pacific/Wallis` - Pacific/Wallis
     * * `Pacific/Yap` - Pacific/Yap
     * * `Poland` - Poland
     * * `Portugal` - Portugal
     * * `ROC` - ROC
     * * `ROK` - ROK
     * * `Singapore` - Singapore
     * * `Turkey` - Turkey
     * * `UCT` - UCT
     * * `US/Alaska` - US/Alaska
     * * `US/Aleutian` - US/Aleutian
     * * `US/Arizona` - US/Arizona
     * * `US/Central` - US/Central
     * * `US/East-Indiana` - US/East-Indiana
     * * `US/Eastern` - US/Eastern
     * * `US/Hawaii` - US/Hawaii
     * * `US/Indiana-Starke` - US/Indiana-Starke
     * * `US/Michigan` - US/Michigan
     * * `US/Mountain` - US/Mountain
     * * `US/Pacific` - US/Pacific
     * * `US/Samoa` - US/Samoa
     * * `UTC` - UTC
     * * `Universal` - Universal
     * * `W-SU` - W-SU
     * * `WET` - WET
     * * `Zulu` - Zulu */
    timezone?: string
    /** Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`). */
    data_attributes?: unknown
    /**
     * Ordered list of person properties used to render a human-friendly display name in the UI.
     * @nullable
     * @items.maxLength 400
     */
    person_display_name_properties?: string[] | null
    correlation_config?: unknown
    /**
     * Disables posthog-js autocapture (clicks, page views) when true.
     * @nullable
     */
    autocapture_opt_out?: boolean | null
    /**
     * Enables automatic capture of JavaScript exceptions via the SDK.
     * @nullable
     */
    autocapture_exceptions_opt_in?: boolean | null
    /**
     * Enables automatic capture of Core Web Vitals performance metrics.
     * @nullable
     */
    autocapture_web_vitals_opt_in?: boolean | null
    autocapture_web_vitals_allowed_metrics?: unknown
    autocapture_exceptions_errors_to_ignore?: unknown
    /**
     * Enables capturing browser console logs alongside session replays.
     * @nullable
     */
    capture_console_log_opt_in?: boolean | null
    /**
     * Enables capturing performance timing and network requests.
     * @nullable
     */
    capture_performance_opt_in?: boolean | null
    /** Enables session replay recording for this project. */
    session_recording_opt_in?: boolean
    /**
     * Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).
     * @nullable
     * @pattern ^-?\d{0,1}(?:\.\d{0,2})?$
     */
    session_recording_sample_rate?: string | null
    /**
     * Skip saving sessions shorter than this many milliseconds.
     * @minimum 0
     * @maximum 30000
     * @nullable
     */
    session_recording_minimum_duration_milliseconds?: number | null
    session_recording_linked_flag?: unknown
    session_recording_network_payload_capture_config?: unknown
    session_recording_masking_config?: unknown
    /** @nullable */
    session_recording_url_trigger_config?: unknown[] | null
    /** @nullable */
    session_recording_url_blocklist_config?: unknown[] | null
    /** @nullable */
    session_recording_event_trigger_config?: (string | null)[] | null
    /**
     * @maxLength 24
     * @nullable
     */
    session_recording_trigger_match_type_config?: string | null
    /** V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields. */
    session_recording_trigger_groups?: unknown
    /** How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).
     *
     * * `30d` - 30 Days
     * * `90d` - 90 Days
     * * `1y` - 1 Year
     * * `5y` - 5 Years */
    session_recording_retention_period?: SessionRecordingRetentionPeriodEnumApi
    session_replay_config?: unknown
    survey_config?: unknown
    access_control?: boolean
    /** First day of the week for date range filters. 0 = Sunday, 1 = Monday.
     *
     * * `0` - Sunday
     * * `1` - Monday */
    week_start_day?: WeekStartDayEnumApi | null
    /**
     * ID of the dashboard shown as the project's default landing dashboard.
     * @nullable
     */
    primary_dashboard?: number | null
    /** @nullable */
    live_events_columns?: string[] | null
    /**
     * Origins permitted to record session replays and heatmaps. Empty list allows all origins.
     * @nullable
     * @items.maxLength 200
     */
    recording_domains?: (string | null)[] | null
    readonly person_on_events_querying_enabled?: boolean
    /** @nullable */
    inject_web_apps?: boolean | null
    extra_settings?: unknown
    modifiers?: unknown
    readonly default_modifiers?: PatchedProjectBackwardCompatApiDefaultModifiers
    has_completed_onboarding_for?: unknown
    /**
     * Enables displaying surveys via posthog-js on allowed origins.
     * @nullable
     */
    surveys_opt_in?: boolean | null
    /**
     * Enables heatmap recording on pages that host posthog-js.
     * @nullable
     */
    heatmaps_opt_in?: boolean | null
    readonly product_intents?: readonly PatchedProjectBackwardCompatApiProductIntentsItem[]
    /**
     * Default value for the `persist` option on newly created feature flags.
     * @nullable
     */
    flags_persistence_default?: boolean | null
    /** @nullable */
    readonly secret_api_token?: string | null
    /** @nullable */
    readonly secret_api_token_backup?: string | null
    /** @nullable */
    receive_org_level_activity_logs?: boolean | null
    /** Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.
     *
     * * `b2b` - B2B
     * * `b2c` - B2C
     * * `other` - Other */
    business_model?: BusinessModelEnumApi | BlankEnumApi | null
    /**
     * Enables the customer conversations / live chat product for this project.
     * @nullable
     */
    conversations_enabled?: boolean | null
    conversations_settings?: unknown
    logs_settings?: unknown
    /** @nullable */
    proactive_tasks_enabled?: boolean | null
    readonly available_setup_task_ids?: readonly AvailableSetupTaskIdsEnumApi[]
    /**
     * Set to True when project deletion has been initiated. Blocks UI access to this project until the async task completes.
     * @nullable
     */
    readonly is_pending_deletion?: boolean | null
    /** ID of the project this environment belongs to. */
    readonly project_id?: number
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level?: string | null
    readonly managed_viewsets?: PatchedProjectBackwardCompatApiManagedViewsets
    revenue_analytics_config?: TeamRevenueAnalyticsConfigApi
    marketing_analytics_config?: TeamMarketingAnalyticsConfigApi
    customer_analytics_config?: TeamCustomerAnalyticsConfigApi
    workflows_config?: TeamWorkflowsConfigApi
    base_currency?: BaseCurrencyEnumApi
    /**
     * Enables capturing clicks that had no effect (rage-click detection).
     * @nullable
     */
    capture_dead_clicks?: boolean | null
    cookieless_server_hash_mode?: CookielessServerHashModeEnumApi | null
    /** @nullable */
    human_friendly_comparison_periods?: boolean | null
    /** @nullable */
    feature_flag_confirmation_enabled?: boolean | null
    /** @nullable */
    feature_flag_confirmation_message?: string | null
    /**
     * Whether to automatically apply default evaluation contexts to new feature flags
     * @nullable
     */
    default_evaluation_contexts_enabled?: boolean | null
    /**
     * Whether to require at least one evaluation context tag when creating new feature flags
     * @nullable
     */
    require_evaluation_contexts?: boolean | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    default_data_theme?: number | null
    onboarding_tasks?: unknown
    /** @nullable */
    web_analytics_pre_aggregated_tables_enabled?: boolean | null
    /** The team's events data retention window in months (plan-derived, synced from billing). When retention enforcement is active for the team, queries do not return events older than this many months. */
    readonly event_retention_months?: number
    /** Whether events data retention is currently enforced for this team (cohort/flag gated). */
    readonly events_retention_enforced?: boolean
}

export interface SharePasswordApi {
    readonly id: number
    readonly created_at: string
    /**
     * @maxLength 100
     * @nullable
     */
    note?: string | null
    readonly created_by_email: string
    readonly is_active: boolean
}

export interface SharingConfigurationApi {
    readonly created_at: string
    enabled?: boolean
    /** @nullable */
    readonly access_token: string | null
    settings?: unknown
    password_required?: boolean
    readonly share_passwords: readonly SharePasswordApi[]
}

export interface FileSystemApi {
    readonly id: string
    path: string
    /** @nullable */
    readonly depth: number | null
    /** @maxLength 100 */
    type?: string
    /**
     * @maxLength 100
     * @nullable
     */
    ref?: string | null
    /** @nullable */
    href?: string | null
    meta?: unknown
    /** @nullable */
    shortcut?: boolean | null
    readonly created_at: string
    /** @nullable */
    readonly last_viewed_at: string | null
    /**
     * Resolved access level the user has for the object this entry references ('none' means the user can't open it). Null when access controls don't apply to the entry type.
     * @nullable
     */
    readonly user_access_level: string | null
}

export interface PaginatedFileSystemListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: FileSystemApi[]
}

export interface PatchedFileSystemApi {
    readonly id?: string
    path?: string
    /** @nullable */
    readonly depth?: number | null
    /** @maxLength 100 */
    type?: string
    /**
     * @maxLength 100
     * @nullable
     */
    ref?: string | null
    /** @nullable */
    href?: string | null
    meta?: unknown
    /** @nullable */
    shortcut?: boolean | null
    readonly created_at?: string
    /** @nullable */
    readonly last_viewed_at?: string | null
    /**
     * Resolved access level the user has for the object this entry references ('none' means the user can't open it). Null when access controls don't apply to the entry type.
     * @nullable
     */
    readonly user_access_level?: string | null
}

/**
 * Payload for publishing a freeform canvas's React source via the agent.
 */
export interface PatchedCanvasPublishApi {
    code?: string
    prompt?: string
    name?: string
}

export interface ContextGenerationApi {
    /**
     * ID of the Task currently generating this folder's CONTEXT.md, or null if none.
     * @nullable
     */
    task_id: string | null
}

export interface ContextGenerationSetApi {
    /**
     * ID of the Task generating this folder's CONTEXT.md. Must reference a Task in the same team. Set to null to clear the association.
     * @nullable
     */
    task_id: string | null
}

export interface FolderInstructionsApi {
    /** Unique identifier for this instructions version. */
    readonly id: string
    /** Markdown instructions describing the contents of the folder. */
    readonly content: string
    /** Monotonically increasing version number, starting at 1. */
    readonly version: number
    /** Whether this is the current (latest) version for the folder. */
    readonly is_latest: boolean
    /** User who published this version. */
    readonly created_by: UserBasicApi
    /** When this version was published. */
    readonly created_at: string
    /** When this version row was last modified. */
    readonly updated_at: string
}

export interface FolderInstructionsPublishApi {
    /** Full markdown instructions to publish as a new version for the folder. */
    content: string
    /**
     * Latest version you are editing from, for optimistic concurrency. If provided and the folder's instructions have changed since, the request fails with 409. Use 0 when no instructions exist yet.
     * @minimum 0
     */
    base_version?: number
}

export interface PatchedFolderInstructionsPublishApi {
    /** Full markdown instructions to publish as a new version for the folder. */
    content?: string
    /**
     * Latest version you are editing from, for optimistic concurrency. If provided and the folder's instructions have changed since, the request fails with 409. Use 0 when no instructions exist yet.
     * @minimum 0
     */
    base_version?: number
}

/**
 * Version-history entry: metadata only, with the markdown content omitted.
 */
export interface FolderInstructionsVersionApi {
    /** Unique identifier for this instructions version. */
    readonly id: string
    /** Monotonically increasing version number, starting at 1. */
    readonly version: number
    /** Whether this is the current (latest) version for the folder. */
    readonly is_latest: boolean
    /** User who published this version. */
    readonly created_by: UserBasicApi
    /** When this version was published. */
    readonly created_at: string
}

export interface PaginatedFolderInstructionsVersionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: FolderInstructionsVersionApi[]
}

export interface FileSystemShortcutApi {
    readonly id: string
    /** Display path of the shortcut in the sidebar. */
    path: string
    /**
     * Type of the linked item (e.g. 'folder', 'insight'), or blank.
     * @maxLength 100
     */
    type?: string
    /**
     * Reference to the linked item, scoped to its type. Null for href-only shortcuts.
     * @maxLength 100
     * @nullable
     */
    ref?: string | null
    /**
     * Destination URL the shortcut opens. Null when the shortcut points at an item by ref.
     * @nullable
     */
    href?: string | null
    /**
     * Display order within the user's shortcut list, ascending.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order?: number
    readonly created_at: string
    /**
     * Resolved access level the user has for the object this entry references ('none' means the user can't open it). Null when access controls don't apply to the entry type.
     * @nullable
     */
    readonly user_access_level: string | null
}

export interface PaginatedFileSystemShortcutListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: FileSystemShortcutApi[]
}

export interface PatchedFileSystemShortcutApi {
    readonly id?: string
    /** Display path of the shortcut in the sidebar. */
    path?: string
    /**
     * Type of the linked item (e.g. 'folder', 'insight'), or blank.
     * @maxLength 100
     */
    type?: string
    /**
     * Reference to the linked item, scoped to its type. Null for href-only shortcuts.
     * @maxLength 100
     * @nullable
     */
    ref?: string | null
    /**
     * Destination URL the shortcut opens. Null when the shortcut points at an item by ref.
     * @nullable
     */
    href?: string | null
    /**
     * Display order within the user's shortcut list, ascending.
     * @minimum -2147483648
     * @maximum 2147483647
     */
    order?: number
    readonly created_at?: string
    /**
     * Resolved access level the user has for the object this entry references ('none' means the user can't open it). Null when access controls don't apply to the entry type.
     * @nullable
     */
    readonly user_access_level?: string | null
}

export interface FileSystemShortcutReorderApi {
    /** IDs of the current user's shortcuts in the desired display order. */
    ordered_ids: string[]
}

/**
 * * `image/png` - image/png
 * * `application/pdf` - application/pdf
 * * `text/csv` - text/csv
 * * `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
 * * `video/webm` - video/webm
 * * `video/mp4` - video/mp4
 * * `image/gif` - image/gif
 * * `application/json` - application/json
 */
export type ExportFormatEnumApi = (typeof ExportFormatEnumApi)[keyof typeof ExportFormatEnumApi]

export const ExportFormatEnumApi = {
    ImagePng: 'image/png',
    ApplicationPdf: 'application/pdf',
    TextCsv: 'text/csv',
    ApplicationVndopenxmlformatsOfficedocumentspreadsheetmlsheet:
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    VideoWebm: 'video/webm',
    VideoMp4: 'video/mp4',
    ImageGif: 'image/gif',
    ApplicationJson: 'application/json',
} as const

/**
 * Standard ExportedAsset serializer that doesn't return content.
 */
export interface ExportedAssetApi {
    readonly id: number
    /** @nullable */
    dashboard?: number | null
    /** @nullable */
    insight?: number | null
    export_format: ExportFormatEnumApi
    readonly created_at: string
    readonly has_content: boolean
    export_context?: unknown
    readonly filename: string
    /** @nullable */
    readonly expires_after: string | null
    /** @nullable */
    readonly exception: string | null
    /**
     * The effective access level the user has for this object
     * @nullable
     */
    readonly user_access_level: string | null
}

export interface PaginatedExportedAssetListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExportedAssetApi[]
}

/**
 * * `conversations` - conversations
 * * `error_tracking` - error_tracking
 * * `session_replay` - session_replay
 */
export type ProductsEnumApi = (typeof ProductsEnumApi)[keyof typeof ProductsEnumApi]

export const ProductsEnumApi = {
    Conversations: 'conversations',
    ErrorTracking: 'error_tracking',
    SessionReplay: 'session_replay',
} as const

export interface ProductEnablementApi {
    /**
     * Products to turn on for this project, each enabled with server-owned conservative defaults.
     * @minItems 1
     */
    products: ProductsEnumApi[]
}

/**
 * Per requested product: "enabled" (just turned on) or "already_enabled".
 */
export type ProductEnablementResultApiResults = { [key: string]: string }

export interface ProductEnablementResultApi {
    /** Per requested product: "enabled" (just turned on) or "already_enabled". */
    results: ProductEnablementResultApiResults
}

export interface ProjectSecretAPIKeyApi {
    readonly id: string
    /** @maxLength 40 */
    label: string
    readonly value: string
    /** @nullable */
    readonly mask_value: string | null
    readonly created_at: string
    readonly created_by: UserBasicApi
    /** @nullable */
    readonly last_used_at: string | null
    /** @nullable */
    readonly last_rolled_at: string | null
    /** Project-wide API scopes granted to this key. Project secret API keys do not honor object-level access controls, so a scope can access resources of that type even when per-resource RBAC would hide them from an individual user. */
    scopes: string[]
}

export interface PaginatedProjectSecretAPIKeyListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ProjectSecretAPIKeyApi[]
}

export interface PatchedProjectSecretAPIKeyApi {
    readonly id?: string
    /** @maxLength 40 */
    label?: string
    readonly value?: string
    /** @nullable */
    readonly mask_value?: string | null
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    /** @nullable */
    readonly last_used_at?: string | null
    /** @nullable */
    readonly last_rolled_at?: string | null
    /** Project-wide API scopes granted to this key. Project secret API keys do not honor object-level access controls, so a scope can access resources of that type even when per-resource RBAC would hide them from an individual user. */
    scopes?: string[]
}

/**
 * * `DateTime` - DateTime
 * * `String` - String
 * * `Numeric` - Numeric
 * * `Boolean` - Boolean
 * * `Duration` - Duration
 */
export type PropertyDefinitionTypeEnumApi =
    (typeof PropertyDefinitionTypeEnumApi)[keyof typeof PropertyDefinitionTypeEnumApi]

export const PropertyDefinitionTypeEnumApi = {
    DateTime: 'DateTime',
    String: 'String',
    Numeric: 'Numeric',
    Boolean: 'Boolean',
    Duration: 'Duration',
} as const

/**
 * Serializer mixin that handles tags for objects.
 */
export interface EnterprisePropertyDefinitionApi {
    readonly id: string
    readonly name: string
    /** @nullable */
    description?: string | null
    tags?: unknown[]
    readonly is_numerical: boolean
    readonly updated_at: string
    readonly updated_by: UserBasicApi
    /** @nullable */
    readonly is_seen_on_filtered_events: boolean | null
    property_type?: PropertyDefinitionTypeEnumApi | BlankEnumApi | null
    verified?: boolean
    /** @nullable */
    readonly verified_at: string | null
    readonly verified_by: UserBasicApi
    /** @nullable */
    hidden?: boolean | null
}

export interface PaginatedEnterprisePropertyDefinitionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: EnterprisePropertyDefinitionApi[]
}

/**
 * Serializer mixin that handles tags for objects.
 */
export interface PatchedEnterprisePropertyDefinitionApi {
    readonly id?: string
    readonly name?: string
    /** @nullable */
    description?: string | null
    tags?: unknown[]
    readonly is_numerical?: boolean
    readonly updated_at?: string
    readonly updated_by?: UserBasicApi
    /** @nullable */
    readonly is_seen_on_filtered_events?: boolean | null
    property_type?: PropertyDefinitionTypeEnumApi | BlankEnumApi | null
    verified?: boolean
    /** @nullable */
    readonly verified_at?: string | null
    readonly verified_by?: UserBasicApi
    /** @nullable */
    hidden?: boolean | null
}

/**
 * * `add` - add
 * * `remove` - remove
 * * `set` - set
 */
export type BulkUpdateTagsActionEnumApi = (typeof BulkUpdateTagsActionEnumApi)[keyof typeof BulkUpdateTagsActionEnumApi]

export const BulkUpdateTagsActionEnumApi = {
    Add: 'add',
    Remove: 'remove',
    Set: 'set',
} as const

export interface BulkUpdateTagsRequestApi {
    /**
     * List of object IDs to update tags on.
     * @maxItems 500
     */
    ids: number[]
    /** 'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.
     *
     * * `add` - add
     * * `remove` - remove
     * * `set` - set */
    action: BulkUpdateTagsActionEnumApi
    /** Tag names to add, remove, or set. */
    tags: string[]
}

export interface BulkUpdateTagsItemApi {
    id: number
    tags: string[]
}

export interface BulkUpdateTagsErrorApi {
    id: number
    reason: string
}

export interface BulkUpdateTagsResponseApi {
    updated: BulkUpdateTagsItemApi[]
    skipped: BulkUpdateTagsErrorApi[]
}

/**
 * * `disabled` - disabled
 * * `toolbar` - toolbar
 */
export type ToolbarModeEnumApi = (typeof ToolbarModeEnumApi)[keyof typeof ToolbarModeEnumApi]

export const ToolbarModeEnumApi = {
    Disabled: 'disabled',
    Toolbar: 'toolbar',
} as const

/**
 * Serializer for `Team` model with minimal attributes to speeed up loading and transfer times.
 * Also used for nested serializers.
 */
export interface TeamBasicApi {
    readonly id: number
    readonly uuid: string
    readonly organization: string
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    readonly project_id: number
    readonly api_token: string
    readonly name: string
    readonly completed_snippet_onboarding: boolean
    readonly has_completed_onboarding_for: unknown
    readonly ingested_event: boolean
    readonly is_demo: boolean
    readonly timezone: string
    readonly access_control: boolean
}

/**
 * * `0` - none
 * * `3` - config
 * * `6` - install
 * * `9` - root
 */
export type PluginsAccessLevelEnumApi = (typeof PluginsAccessLevelEnumApi)[keyof typeof PluginsAccessLevelEnumApi]

export const PluginsAccessLevelEnumApi = {
    Number0: 0,
    Number3: 3,
    Number6: 6,
    Number9: 9,
} as const

/**
 * * `bayesian` - Bayesian
 * * `frequentist` - Frequentist
 */
export type DefaultExperimentStatsMethodEnumApi =
    (typeof DefaultExperimentStatsMethodEnumApi)[keyof typeof DefaultExperimentStatsMethodEnumApi]

export const DefaultExperimentStatsMethodEnumApi = {
    Bayesian: 'bayesian',
    Frequentist: 'frequentist',
} as const

export type OrganizationApiTeamsItem = { [key: string]: unknown }

export type OrganizationApiProjectsItem = { [key: string]: unknown }

export type OrganizationApiMetadata = { [key: string]: string }

export type OrganizationApiEnrichment = { [key: string]: unknown }

export interface OrganizationApi {
    readonly id: string
    /** @maxLength 64 */
    name: string
    /** @pattern ^[-a-zA-Z0-9_]+$ */
    readonly slug: string
    /** @nullable */
    logo_media_id?: string | null
    readonly created_at: string
    readonly updated_at: string
    readonly membership_level: EffectiveMembershipLevelEnumApi
    readonly plugins_access_level: PluginsAccessLevelEnumApi
    readonly teams: readonly OrganizationApiTeamsItem[]
    readonly projects: readonly OrganizationApiProjectsItem[]
    /** @nullable */
    readonly available_product_features: readonly unknown[] | null
    /** Legacy field; member-join emails are controlled per user in account notification settings. */
    readonly is_member_join_email_enabled: boolean
    readonly metadata: OrganizationApiMetadata
    /** @nullable */
    readonly customer_id: string | null
    /** @nullable */
    enforce_2fa?: boolean | null
    /** @nullable */
    members_can_invite?: boolean | null
    /**
     * When True, organization members (below admin) are allowed to create new projects. Admins and owners can always create projects.
     * @nullable
     */
    members_can_create_projects?: boolean | null
    members_can_use_personal_api_keys?: boolean
    allow_publicly_shared_resources?: boolean
    readonly member_count: number
    /** @nullable */
    is_ai_data_processing_approved?: boolean | null
    /**
     * When True, this organization allows its data to be used to train PostHog AI models.
     * @nullable
     */
    is_ai_training_opted_in?: boolean | null
    /**
     * When True, the AI training opt-out setting cannot be modified through the UI or API.
     * @nullable
     */
    readonly is_ai_training_locked: boolean | null
    /**
     * When True, in-app callouts inviting members to enable AI training are shown.
     * @nullable
     */
    readonly is_ai_training_cta_shown: boolean | null
    /** @nullable */
    readonly is_hipaa: boolean | null
    /** Default statistical method for new experiments in this organization.
     *
     * * `bayesian` - Bayesian
     * * `frequentist` - Frequentist */
    default_experiment_stats_method?: DefaultExperimentStatsMethodEnumApi | BlankEnumApi | null
    /** Default setting for 'Discard client IP data' for new projects in this organization. */
    default_anonymize_ips?: boolean
    /**
     * ID of the role to automatically assign to new members joining the organization
     * @nullable
     */
    default_role_id?: string | null
    /**
     * Set this to 'No' to temporarily disable an organization.
     * @nullable
     */
    readonly is_active: boolean | null
    /**
     * (optional) reason for why the organization has been de-activated. This will be displayed to users on the web app.
     * @nullable
     */
    readonly is_not_active_reason: string | null
    /**
     * Set to True when org deletion has been initiated. Blocks all UI access until the async task completes.
     * @nullable
     */
    readonly is_pending_deletion: boolean | null
    readonly enrichment: OrganizationApiEnrichment
}

/**
 * Serializer for `Organization` model with minimal attributes to speeed up loading and transfer times.
 * Also used for nested serializers.
 */
export interface OrganizationBasicApi {
    readonly id: string
    /** @maxLength 64 */
    name: string
    /**
     * @maxLength 48
     * @pattern ^[-a-zA-Z0-9_]+$
     */
    slug: string
    /** @nullable */
    readonly logo_media_id: string | null
    readonly membership_level: EffectiveMembershipLevelEnumApi
    members_can_use_personal_api_keys?: boolean
    /**
     * Set this to 'No' to temporarily disable an organization.
     * @nullable
     */
    is_active?: boolean | null
    /**
     * (optional) reason for why the organization has been de-activated. This will be displayed to users on the web app.
     * @maxLength 200
     * @nullable
     */
    is_not_active_reason?: string | null
    /**
     * Set to True when org deletion has been initiated. Blocks all UI access until the async task completes.
     * @nullable
     */
    is_pending_deletion?: boolean | null
}

export interface ScenePersonalisationBasicApi {
    /** @maxLength 200 */
    scene: string
    /** @nullable */
    dashboard?: number | null
}

/**
 * * `light` - Light
 * * `dark` - Dark
 * * `system` - System
 */
export type ThemeModeEnumApi = (typeof ThemeModeEnumApi)[keyof typeof ThemeModeEnumApi]

export const ThemeModeEnumApi = {
    Light: 'light',
    Dark: 'dark',
    System: 'system',
} as const

/**
 * * `above` - Above
 * * `below` - Below
 * * `hidden` - Hidden
 */
export type ShortcutPositionEnumApi = (typeof ShortcutPositionEnumApi)[keyof typeof ShortcutPositionEnumApi]

export const ShortcutPositionEnumApi = {
    Above: 'above',
    Below: 'below',
    Hidden: 'hidden',
} as const

/**
 * * `delegated` - Delegated to teammate
 * * `later` - Skipped for later
 * * `other` - Other
 */
export type OnboardingSkippedReasonEnumApi =
    (typeof OnboardingSkippedReasonEnumApi)[keyof typeof OnboardingSkippedReasonEnumApi]

export const OnboardingSkippedReasonEnumApi = {
    Delegated: 'delegated',
    Later: 'later',
    Other: 'other',
} as const

/**
 * Shape of each item in UserSerializer.pending_invites.
 */
export interface PendingInviteApi {
    id: string
    target_email: string
    organization_id: string
    organization_name: string
    created_at: string
}

/**
 * Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.
 */
export type UserApiNotificationSettings = { [key: string]: unknown }

export interface UserApi {
    readonly date_joined: string
    readonly uuid: string
    /** @nullable */
    readonly distinct_id: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    readonly pending_email: string | null
    /** @nullable */
    readonly is_email_verified: boolean | null
    /** Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is. */
    notification_settings?: UserApiNotificationSettings
    /**
     * Whether PostHog should anonymize events captured for this user when identified.
     * @nullable
     */
    anonymize_data?: boolean | null
    /** @nullable */
    allow_impersonation?: boolean | null
    toolbar_mode?: ToolbarModeEnumApi | BlankEnumApi | null
    readonly has_password: boolean
    readonly id: number
    /** Designates whether the user can log into this admin site. */
    is_staff?: boolean
    /** @nullable */
    readonly is_impersonated: boolean | null
    /** @nullable */
    readonly is_impersonated_until: string | null
    /** @nullable */
    readonly is_impersonated_read_only: boolean | null
    /** @nullable */
    readonly sensitive_session_expires_at: string | null
    readonly team: TeamBasicApi
    readonly organization: OrganizationApi
    readonly organizations: readonly OrganizationBasicApi[]
    set_current_organization?: string
    set_current_team?: string
    /** @maxLength 128 */
    password: string
    /** The user's current password. Required when changing `password` if the user already has a usable password set. */
    current_password?: string
    events_column_config?: unknown
    readonly is_2fa_enabled: boolean
    readonly has_social_auth: boolean
    readonly has_sso_enforcement: boolean
    has_seen_product_intro_for?: unknown
    readonly scene_personalisation: readonly ScenePersonalisationBasicApi[]
    theme_mode?: ThemeModeEnumApi | BlankEnumApi | null
    hedgehog_config?: unknown
    /** @nullable */
    allow_sidebar_suggestions?: boolean | null
    shortcut_position?: ShortcutPositionEnumApi | BlankEnumApi | null
    role_at_organization?: RoleAtOrganizationEnumApi
    /**
     * Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.
     * @nullable
     */
    passkeys_enabled_for_2fa?: boolean | null
    /** When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions. */
    hide_mcp_hints?: boolean
    /** @nullable */
    readonly onboarding_skipped_at: string | null
    readonly onboarding_skipped_reason: OnboardingSkippedReasonEnumApi | null
    /** @nullable */
    readonly onboarding_skipped_organization_id: string | null
    /** @nullable */
    readonly onboarding_delegated_to_invite: string | null
    /**
     * Organization ID of the pending delegation invite, if any. Used by the frontend to scope the 'waiting for teammate' UI to the org where delegation was initiated.
     * @nullable
     */
    readonly onboarding_delegated_to_organization_id: string | null
    /** @nullable */
    readonly onboarding_delegation_accepted_at: string | null
    /** @nullable */
    readonly is_organization_first_user: boolean | null
    /** Real-time notification types that currently have a live dispatch site. Drives the in-app notifications settings UI. Read-only. */
    readonly active_realtime_notification_types: readonly string[]
    readonly pending_invites: readonly PendingInviteApi[]
    /** True if the user has at least one Personal API Key or passkey and has not yet acknowledged their existing credentials. Used to gate a one-shot review screen on first post-provisioning login. Becomes False once the user POSTs to `/api/users/@me/credentials_review_complete/`. Read-only. */
    readonly requires_credential_review: boolean
}

export interface PaginatedUserListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: UserApi[]
}

/**
 * Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.
 */
export type PatchedUserApiNotificationSettings = { [key: string]: unknown }

export interface PatchedUserApi {
    readonly date_joined?: string
    readonly uuid?: string
    /** @nullable */
    readonly distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email?: string
    /** @nullable */
    readonly pending_email?: string | null
    /** @nullable */
    readonly is_email_verified?: boolean | null
    /** Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is. */
    notification_settings?: PatchedUserApiNotificationSettings
    /**
     * Whether PostHog should anonymize events captured for this user when identified.
     * @nullable
     */
    anonymize_data?: boolean | null
    /** @nullable */
    allow_impersonation?: boolean | null
    toolbar_mode?: ToolbarModeEnumApi | BlankEnumApi | null
    readonly has_password?: boolean
    readonly id?: number
    /** Designates whether the user can log into this admin site. */
    is_staff?: boolean
    /** @nullable */
    readonly is_impersonated?: boolean | null
    /** @nullable */
    readonly is_impersonated_until?: string | null
    /** @nullable */
    readonly is_impersonated_read_only?: boolean | null
    /** @nullable */
    readonly sensitive_session_expires_at?: string | null
    readonly team?: TeamBasicApi
    readonly organization?: OrganizationApi
    readonly organizations?: readonly OrganizationBasicApi[]
    set_current_organization?: string
    set_current_team?: string
    /** @maxLength 128 */
    password?: string
    /** The user's current password. Required when changing `password` if the user already has a usable password set. */
    current_password?: string
    events_column_config?: unknown
    readonly is_2fa_enabled?: boolean
    readonly has_social_auth?: boolean
    readonly has_sso_enforcement?: boolean
    has_seen_product_intro_for?: unknown
    readonly scene_personalisation?: readonly ScenePersonalisationBasicApi[]
    theme_mode?: ThemeModeEnumApi | BlankEnumApi | null
    hedgehog_config?: unknown
    /** @nullable */
    allow_sidebar_suggestions?: boolean | null
    shortcut_position?: ShortcutPositionEnumApi | BlankEnumApi | null
    role_at_organization?: RoleAtOrganizationEnumApi
    /**
     * Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.
     * @nullable
     */
    passkeys_enabled_for_2fa?: boolean | null
    /** When true, the user has opted out of in-app hints promoting the PostHog MCP integration after taking actions. */
    hide_mcp_hints?: boolean
    /** @nullable */
    readonly onboarding_skipped_at?: string | null
    readonly onboarding_skipped_reason?: OnboardingSkippedReasonEnumApi | null
    /** @nullable */
    readonly onboarding_skipped_organization_id?: string | null
    /** @nullable */
    readonly onboarding_delegated_to_invite?: string | null
    /**
     * Organization ID of the pending delegation invite, if any. Used by the frontend to scope the 'waiting for teammate' UI to the org where delegation was initiated.
     * @nullable
     */
    readonly onboarding_delegated_to_organization_id?: string | null
    /** @nullable */
    readonly onboarding_delegation_accepted_at?: string | null
    /** @nullable */
    readonly is_organization_first_user?: boolean | null
    /** Real-time notification types that currently have a live dispatch site. Drives the in-app notifications settings UI. Read-only. */
    readonly active_realtime_notification_types?: readonly string[]
    readonly pending_invites?: readonly PendingInviteApi[]
    /** True if the user has at least one Personal API Key or passkey and has not yet acknowledged their existing credentials. Used to gate a one-shot review screen on first post-provisioning login. Becomes False once the user POSTs to `/api/users/@me/credentials_review_complete/`. Read-only. */
    readonly requires_credential_review?: boolean
}

export interface UserGitHubAccountApi {
    /**
     * GitHub account type for the installation (e.g. User or Organization).
     * @nullable
     */
    type?: string | null
    /**
     * GitHub login or organization name tied to the installation.
     * @nullable
     */
    name?: string | null
}

export interface UserGitHubIntegrationItemApi {
    /** PostHog UserIntegration row id. */
    id: string
    /** Integration kind; always `github` for this API. */
    kind: string
    /** GitHub App installation id. */
    installation_id: string
    /**
     * Repository selection mode from GitHub (e.g. selected or all).
     * @nullable
     */
    repository_selection?: string | null
    /** Installation account metadata from GitHub. */
    account?: UserGitHubAccountApi | null
    /** True when this installation id matches a team-level GitHub integration on the active project. */
    uses_shared_installation: boolean
    /** When this integration row was created. */
    created_at: string
}

export interface UserGitHubIntegrationListResponseApi {
    /** GitHub personal integrations for the authenticated user. */
    results: UserGitHubIntegrationItemApi[]
}

export interface PaginatedUserGitHubIntegrationListResponseListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: UserGitHubIntegrationListResponseApi[]
}

export interface GitHubBranchesResponseApi {
    /** List of branch names */
    branches: string[]
    /**
     * The default branch of the repository
     * @nullable
     */
    default_branch?: string | null
    /** Whether more branches exist beyond the returned page */
    has_more: boolean
}

export interface GitHubRepoApi {
    /** GitHub repository numeric identifier. */
    id: number
    /** Repository short name (without the owner prefix). */
    name: string
    /** Fully-qualified repository name as 'owner/repo'. */
    full_name: string
    /** Whether the repository is private. */
    private?: boolean
    /** The repository's default branch (e.g. 'main'). */
    default_branch?: string
    /** Primary programming language GitHub detected for the repository. */
    language?: string
    /** ISO 8601 timestamp of the most recent push, useful for sorting by recent activity. */
    pushed_at?: string
    /** Whether the repository is archived. */
    archived?: boolean
    /** Whether the PostHog GitHub App has write access — required to open pull requests. */
    can_push?: boolean
}

export interface GitHubReposResponseApi {
    repositories: GitHubRepoApi[]
    /** Whether more repositories are available beyond this page. */
    has_more: boolean
}

export interface GitHubReposRefreshResponseApi {
    /** The refreshed repository cache. */
    repositories: GitHubRepoApi[]
}

export interface UserGitHubPrepareCallbackRequestApi {
    /** GitHub App installation id being managed on github.com. */
    installation_id: string
}

export interface UserGitHubLinkStartRequestApi {
    /**
     * Optional team/project id (e.g. PostHog Code); web UI uses the session's current team.
     * @nullable
     */
    team_id?: number | null
    /** Optional client hint (e.g. posthog_code) for return routing after OAuth. */
    connect_from?: string
}

export interface UserGitHubLinkStartResponseApi {
    /** URL to open in the browser to install or authorize the GitHub App for this user. */
    install_url: string
    /** OAuth or install flow used for this GitHub connection. */
    connect_flow: string
}

export interface UserSlackLinkableWorkspaceItemApi {
    /** PostHog team/project id owning the Slack workspace install. */
    posthog_team_id: number
    /** PostHog team/project name, for display in a picker. */
    posthog_team_name: string
    /** PostHog organization name owning the team, for picker disambiguation. */
    posthog_organization_name: string
    /** Slack workspace (team) id. */
    slack_team_id: string
    /**
     * Slack workspace display name as known by PostHog.
     * @nullable
     */
    slack_team_name?: string | null
}

export interface UserSlackLinkableWorkspaceListResponseApi {
    /** Slack workspaces the user could link to but hasn't yet. */
    results: UserSlackLinkableWorkspaceItemApi[]
}

/**
 * Settings-initiated link can target a specific PostHog team + Slack workspace.
 *
 * Both are optional — when omitted we fall back to the user's ``current_team``
 * and that team's first Slack ``Integration`` (mirrors ``github_start`` for
 * the simple case). The frontend passes both explicitly once it has the
 * linkable-workspace list and the user has picked a workspace.
 */
export interface UserSlackLinkStartRequestApi {
    /**
     * Optional team/project id to link against; defaults to the user's current team.
     * @nullable
     */
    team_id?: number | null
    /**
     * Specific Slack workspace id to link against, scoped to the team. Disambiguates when one team has multiple Slack integrations (rare).
     * @nullable
     */
    slack_team_id?: string | null
}

export interface UserSlackLinkStartResponseApi {
    /** URL to open in the browser to start the Sign-in-with-Slack flow. */
    install_url: string
}

/**
 * A cookie-auth login session shown on the user's 'Web sessions' screen.
 */
export interface UserAuthSessionApi {
    /** Identifier used to revoke this login session. */
    readonly id: string
    /**
     * When this login session was first created — the original sign-in time.
     * @nullable
     */
    readonly created_at: string | null
    /** When this login session last made a request (refreshed periodically). */
    readonly last_activity: string
    /** Approximate city and country derived from the IP address, if known. */
    readonly location: string
    /** Browser and operating system parsed from the user agent, e.g. 'Chrome 135 on macOS'. */
    readonly device: string
    /** How this session signed in (e.g. password, Google, SAML). */
    readonly login_method: string
    /** Whether this is the login session making the current request. */
    readonly is_current: boolean
}

export interface RevokeOtherSessionsResponseApi {
    /** Number of other login sessions that were revoked. */
    revoked_count: number
}

/**
 * * `later` - Later
 * * `other` - Other
 */
export type OnboardingSkipRequestReasonEnumApi =
    (typeof OnboardingSkipRequestReasonEnumApi)[keyof typeof OnboardingSkipRequestReasonEnumApi]

export const OnboardingSkipRequestReasonEnumApi = {
    Later: 'later',
    Other: 'other',
} as const

/**
 * Request body for POST /api/users/{id}/onboarding/skip/.
 *
 * Source of truth for OpenAPI / generated TS / zod / MCP — bind this serializer at
 * runtime so the contract clients believe is enforced (length cap, choice validation,
 * no extra fields) is actually enforced server-side.
 */
export interface OnboardingSkipRequestApi {
    /** Why the user is leaving onboarding. 'later' keeps them able to return; 'other' is a catch-all. 'delegated' is rejected here — use the delegate endpoint so the delegation invite is created atomically.
     *
     * * `later` - Later
     * * `other` - Other */
    reason: OnboardingSkipRequestReasonEnumApi
    /**
     * Onboarding step key the user was on when skipping, for analytics only.
     * @maxLength 64
     */
    step_at_skip?: string
}

/**
 * * `ios` - iOS
 * * `android` - Android
 * * `web` - Web
 */
export type PushTokenPlatformEnumApi = (typeof PushTokenPlatformEnumApi)[keyof typeof PushTokenPlatformEnumApi]

export const PushTokenPlatformEnumApi = {
    Ios: 'ios',
    Android: 'android',
    Web: 'web',
} as const

export interface UserPushTokenRegisterRequestApi {
    /**
     * Opaque push token issued by the device's platform push service (e.g. an Expo push token).
     * @maxLength 512
     */
    token: string
    /** Device platform the token was issued for. One of `ios`, `android`, or `web`.
     *
     * * `ios` - iOS
     * * `android` - Android
     * * `web` - Web */
    platform: PushTokenPlatformEnumApi
}

export interface UserPushTokenItemApi {
    /** PostHog UserPushToken row id. */
    id: string
    /** Device platform the token was issued for.
     *
     * * `ios` - iOS
     * * `android` - Android
     * * `web` - Web */
    platform: PushTokenPlatformEnumApi
    /** When this token was first registered. */
    created_at: string
    /** Last time the mobile app re-registered this token. */
    last_seen_at: string
}

export interface UserPushTokenUnregisterRequestApi {
    /**
     * The opaque push token to remove for the authenticated user.
     * @maxLength 512
     */
    token: string
}

export type CimdVerificationTokensListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type DomainsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type IdentityProviderConfigsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type InvitesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type OauthApplicationsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type OrganizationsProjectsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}

export type DesktopFileSystemListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}

export type DesktopFileSystemInstructionsVersionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}

export type DesktopFileSystemShortcutListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ExportsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type FileSystemListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * A search term.
     */
    search?: string
}

export type FileSystemShortcutListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type ProjectSecretApiKeysListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type PropertyDefinitionsListParams = {
    /**
     * If sent, response value will have `is_seen_on_filtered_events` populated. JSON-encoded
     * @minLength 1
     */
    event_names?: string
    /**
     * Whether to exclude core properties
     */
    exclude_core_properties?: boolean
    /**
     * Whether to exclude properties marked as hidden
     */
    exclude_hidden?: boolean
    /**
     * Whether to exclude properties that the current user does not have read access to via field-level access control
     */
    exclude_restricted?: boolean
    /**
     * JSON-encoded list of excluded properties
     * @minLength 1
     */
    excluded_properties?: string
    /**
     * Whether to return only properties for events in `event_names`. Note: this event scoping does not apply to feature flag properties ($feature/*), which are global and not tracked per-event; to retrieve feature flags use is_feature_flag=true instead.
     * @nullable
     */
    filter_by_event_names?: boolean | null
    /**
     * What group type is the property for. Only should be set if `type=group`
     */
    group_type_index?: number
    /**
     * Whether to return only (or excluding) feature flag properties ($feature/*). Flags are global, not per-event, so they can't be scoped by event_names/filter_by_event_names — pass is_feature_flag=true to list them all.
     * @nullable
     */
    is_feature_flag?: boolean | null
    /**
     * Whether to return only (or excluding) numerical property definitions
     * @nullable
     */
    is_numerical?: boolean | null
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Comma-separated list of properties to filter
     * @minLength 1
     */
    properties?: string
    /**
     * Searches properties by name
     */
    search?: string
    /**
     * What property definitions to return
     *
     * * `event` - event
     * * `person` - person
     * * `group` - group
     * * `session` - session
     * @minLength 1
     */
    type?: PropertyDefinitionsListType
    /**
     * Filter by verified status. True returns only verified, false returns only unverified.
     * @nullable
     */
    verified?: boolean | null
}

export type PropertyDefinitionsListType = (typeof PropertyDefinitionsListType)[keyof typeof PropertyDefinitionsListType]

export const PropertyDefinitionsListType = {
    Event: 'event',
    Person: 'person',
    Group: 'group',
    Session: 'session',
} as const

export type UsersListParams = {
    email?: string
    is_staff?: boolean
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type UsersIntegrationsListParams = {
    /**
     * Integration kind to list. Defaults to `github` for back-compat with mobile and the Code SDK, which call this endpoint without a query param and expect GitHub-shaped items.
     */
    kind?: UsersIntegrationsListKind
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type UsersIntegrationsListKind = (typeof UsersIntegrationsListKind)[keyof typeof UsersIntegrationsListKind]

export const UsersIntegrationsListKind = {
    Github: 'github',
    Slack: 'slack',
} as const

export type UsersIntegrationsGithubBranchesRetrieveParams = {
    /**
     * Maximum number of branches to return
     * @minimum 1
     * @maximum 1000
     */
    limit?: number
    /**
     * Number of branches to skip
     * @minimum 0
     */
    offset?: number
    /**
     * Repository in owner/repo format
     * @minLength 1
     */
    repo: string
    /**
     * Optional case-insensitive branch name search query.
     */
    search?: string
}

export type UsersIntegrationsGithubReposRetrieveParams = {
    /**
     * Maximum number of repositories to return per request (max 500).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Number of repositories to skip before returning results.
     * @minimum 0
     */
    offset?: number
    /**
     * Optional case-insensitive repository name search query.
     */
    search?: string
}

export type UsersLoginSessionsListParams = {
    email?: string
    is_staff?: boolean
}
