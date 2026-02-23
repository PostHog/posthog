/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - core
 * OpenAPI spec version: 1.0.0
 */
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
     * @maxLength 512
     * @nullable
     */
    saml_entity_id?: string | null
    /**
     * @maxLength 512
     * @nullable
     */
    saml_acs_url?: string | null
    /** @nullable */
    saml_x509_cert?: string | null
    /** Returns whether SCIM is configured and enabled for this domain. */
    readonly has_scim: boolean
    scim_enabled?: boolean
    /** @nullable */
    readonly scim_base_url: string | null
    /** @nullable */
    readonly scim_bearer_token: string | null
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
     * @maxLength 512
     * @nullable
     */
    saml_entity_id?: string | null
    /**
     * @maxLength 512
     * @nullable
     */
    saml_acs_url?: string | null
    /** @nullable */
    saml_x509_cert?: string | null
    /** Returns whether SCIM is configured and enabled for this domain. */
    readonly has_scim?: boolean
    scim_enabled?: boolean
    /** @nullable */
    readonly scim_base_url?: string | null
    /** @nullable */
    readonly scim_bearer_token?: string | null
}

/**
 * * `1` - member
 * `8` - administrator
 * `15` - owner
 */
export type OrganizationMembershipLevelApi =
    (typeof OrganizationMembershipLevelApi)[keyof typeof OrganizationMembershipLevelApi]

export const OrganizationMembershipLevelApi = {
    Number1: 1,
    Number8: 8,
    Number15: 15,
} as const

/**
 * * `engineering` - Engineering
 * `data` - Data
 * `product` - Product Management
 * `founder` - Founder
 * `leadership` - Leadership
 * `marketing` - Marketing
 * `sales` - Sales / Success
 * `other` - Other
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

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null | null

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
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | NullEnumApi | null
}

export interface OrganizationInviteApi {
    readonly id: string
    /** @maxLength 254 */
    target_email: string
    /** @maxLength 30 */
    first_name?: string
    readonly emailing_attempt_made: boolean
    /**
     * @minimum 0
     * @maximum 32767
     */
    level?: OrganizationMembershipLevelApi
    /** Check if invite is older than INVITE_DAYS_VALIDITY days. */
    readonly is_expired: boolean
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    /** @nullable */
    message?: string | null
    /** List of team IDs and corresponding access levels to private projects. */
    private_project_access?: unknown | null
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

export interface OrganizationMemberApi {
    readonly id: string
    readonly user: UserBasicApi
    /**
     * @minimum 0
     * @maximum 32767
     */
    level?: OrganizationMembershipLevelApi
    readonly joined_at: string
    readonly updated_at: string
    readonly is_2fa_enabled: boolean
    readonly has_social_auth: boolean
    readonly last_login: string
}

export interface PaginatedOrganizationMemberListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: OrganizationMemberApi[]
}

export interface PatchedOrganizationMemberApi {
    readonly id?: string
    readonly user?: UserBasicApi
    /**
     * @minimum 0
     * @maximum 32767
     */
    level?: OrganizationMembershipLevelApi
    readonly joined_at?: string
    readonly updated_at?: string
    readonly is_2fa_enabled?: boolean
    readonly has_social_auth?: boolean
    readonly last_login?: string
}

/**
 * Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of
passthrough fields. This allows the meaning of `Team` to change from "project" to "environment" without breaking
backward compatibility of the REST API.
Do not use this in greenfield endpoints!
 */
export interface ProjectBackwardCompatBasicApi {
    readonly id: number
    readonly uuid: string
    readonly organization: string
    readonly api_token: string
    readonly name: string
    readonly completed_snippet_onboarding: boolean
    readonly has_completed_onboarding_for: unknown | null
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

export type EffectiveMembershipLevelEnumApi =
    (typeof EffectiveMembershipLevelEnumApi)[keyof typeof EffectiveMembershipLevelEnumApi]

export const EffectiveMembershipLevelEnumApi = {
    Number1: 1,
    Number8: 8,
    Number15: 15,
} as const

/**
 * * `0` - Sunday
 * `1` - Monday
 */
export type WeekStartDayEnumApi = (typeof WeekStartDayEnumApi)[keyof typeof WeekStartDayEnumApi]

export const WeekStartDayEnumApi = {
    Number0: 0,
    Number1: 1,
} as const

/**
 * * `b2b` - B2B
 * `b2c` - B2C
 * `other` - Other
 */
export type BusinessModelEnumApi = (typeof BusinessModelEnumApi)[keyof typeof BusinessModelEnumApi]

export const BusinessModelEnumApi = {
    B2b: 'b2b',
    B2c: 'b2c',
    Other: 'other',
} as const

/**
 * * `ingest_first_event` - ingest_first_event
 * `set_up_reverse_proxy` - set_up_reverse_proxy
 * `create_first_insight` - create_first_insight
 * `create_first_dashboard` - create_first_dashboard
 * `track_custom_events` - track_custom_events
 * `define_actions` - define_actions
 * `set_up_cohorts` - set_up_cohorts
 * `explore_trends_insight` - explore_trends_insight
 * `create_funnel` - create_funnel
 * `explore_retention_insight` - explore_retention_insight
 * `explore_paths_insight` - explore_paths_insight
 * `explore_stickiness_insight` - explore_stickiness_insight
 * `explore_lifecycle_insight` - explore_lifecycle_insight
 * `add_authorized_domain` - add_authorized_domain
 * `set_up_web_vitals` - set_up_web_vitals
 * `review_web_analytics_dashboard` - review_web_analytics_dashboard
 * `filter_web_analytics` - filter_web_analytics
 * `set_up_web_analytics_conversion_goals` - set_up_web_analytics_conversion_goals
 * `visit_web_vitals_dashboard` - visit_web_vitals_dashboard
 * `setup_session_recordings` - setup_session_recordings
 * `watch_session_recording` - watch_session_recording
 * `configure_recording_settings` - configure_recording_settings
 * `create_recording_playlist` - create_recording_playlist
 * `enable_console_logs` - enable_console_logs
 * `create_feature_flag` - create_feature_flag
 * `implement_flag_in_code` - implement_flag_in_code
 * `update_feature_flag_release_conditions` - update_feature_flag_release_conditions
 * `create_multivariate_flag` - create_multivariate_flag
 * `set_up_flag_payloads` - set_up_flag_payloads
 * `set_up_flag_evaluation_runtimes` - set_up_flag_evaluation_runtimes
 * `create_experiment` - create_experiment
 * `implement_experiment_variants` - implement_experiment_variants
 * `launch_experiment` - launch_experiment
 * `review_experiment_results` - review_experiment_results
 * `create_survey` - create_survey
 * `launch_survey` - launch_survey
 * `collect_survey_responses` - collect_survey_responses
 * `connect_source` - connect_source
 * `run_first_query` - run_first_query
 * `join_external_data` - join_external_data
 * `create_saved_view` - create_saved_view
 * `enable_error_tracking` - enable_error_tracking
 * `upload_source_maps` - upload_source_maps
 * `view_first_error` - view_first_error
 * `resolve_first_error` - resolve_first_error
 * `ingest_first_llm_event` - ingest_first_llm_event
 * `view_first_trace` - view_first_trace
 * `track_costs` - track_costs
 * `set_up_llm_evaluation` - set_up_llm_evaluation
 * `run_ai_playground` - run_ai_playground
 * `enable_revenue_analytics_viewset` - enable_revenue_analytics_viewset
 * `connect_revenue_source` - connect_revenue_source
 * `set_up_revenue_goal` - set_up_revenue_goal
 * `enable_log_capture` - enable_log_capture
 * `view_first_logs` - view_first_logs
 * `create_first_workflow` - create_first_workflow
 * `set_up_first_workflow_channel` - set_up_first_workflow_channel
 * `configure_workflow_trigger` - configure_workflow_trigger
 * `add_workflow_action` - add_workflow_action
 * `launch_workflow` - launch_workflow
 * `create_first_endpoint` - create_first_endpoint
 * `configure_endpoint` - configure_endpoint
 * `test_endpoint` - test_endpoint
 * `create_early_access_feature` - create_early_access_feature
 * `update_feature_stage` - update_feature_stage
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
} as const

/**
 * Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of
passthrough fields. This allows the meaning of `Team` to change from "project" to "environment" without breaking
backward compatibility of the REST API.
Do not use this in greenfield endpoints!
 */
export interface ProjectBackwardCompatApi {
    readonly id: number
    readonly organization: string
    /**
     * @minLength 1
     * @maxLength 200
     */
    name?: string
    /**
     * @maxLength 1000
     * @nullable
     */
    product_description?: string | null
    readonly created_at: string
    readonly effective_membership_level: EffectiveMembershipLevelEnumApi | null
    readonly has_group_types: boolean
    readonly group_types: readonly ProjectBackwardCompatApiGroupTypesItem[]
    /** @nullable */
    readonly live_events_token: string | null
    readonly updated_at: string
    readonly uuid: string
    readonly api_token: string
    app_urls?: (string | null)[]
    /**
     * @maxLength 500
     * @nullable
     */
    slack_incoming_webhook?: string | null
    anonymize_ips?: boolean
    completed_snippet_onboarding?: boolean
    readonly ingested_event: boolean
    test_account_filters?: unknown
    /** @nullable */
    test_account_filters_default_checked?: boolean | null
    path_cleaning_filters?: unknown | null
    is_demo?: boolean
    timezone?: string
    data_attributes?: unknown
    /** @nullable */
    person_display_name_properties?: string[] | null
    correlation_config?: unknown | null
    /** @nullable */
    autocapture_opt_out?: boolean | null
    /** @nullable */
    autocapture_exceptions_opt_in?: boolean | null
    /** @nullable */
    autocapture_web_vitals_opt_in?: boolean | null
    autocapture_web_vitals_allowed_metrics?: unknown | null
    autocapture_exceptions_errors_to_ignore?: unknown | null
    /** @nullable */
    capture_console_log_opt_in?: boolean | null
    /** @nullable */
    capture_performance_opt_in?: boolean | null
    session_recording_opt_in?: boolean
    /**
     * @nullable
     * @pattern ^-?\d{0,1}(?:\.\d{0,2})?$
     */
    session_recording_sample_rate?: string | null
    /**
     * @minimum 0
     * @maximum 30000
     * @nullable
     */
    session_recording_minimum_duration_milliseconds?: number | null
    session_recording_linked_flag?: unknown | null
    session_recording_network_payload_capture_config?: unknown | null
    session_recording_masking_config?: unknown | null
    session_replay_config?: unknown | null
    survey_config?: unknown | null
    access_control?: boolean
    /**
     * @minimum -32768
     * @maximum 32767
     */
    week_start_day?: WeekStartDayEnumApi | NullEnumApi | null
    /** @nullable */
    primary_dashboard?: number | null
    /** @nullable */
    live_events_columns?: string[] | null
    /** @nullable */
    recording_domains?: (string | null)[] | null
    readonly person_on_events_querying_enabled: string
    /** @nullable */
    inject_web_apps?: boolean | null
    extra_settings?: unknown | null
    modifiers?: unknown | null
    readonly default_modifiers: string
    has_completed_onboarding_for?: unknown | null
    /** @nullable */
    surveys_opt_in?: boolean | null
    /** @nullable */
    heatmaps_opt_in?: boolean | null
    readonly product_intents: string
    /** @nullable */
    flags_persistence_default?: boolean | null
    /** @nullable */
    readonly secret_api_token: string | null
    /** @nullable */
    readonly secret_api_token_backup: string | null
    /** @nullable */
    receive_org_level_activity_logs?: boolean | null
    /** Whether this project serves B2B or B2C customers, used to optimize the UI layout.

* `b2b` - B2B
* `b2c` - B2C
* `other` - Other */
    business_model?: BusinessModelEnumApi | BlankEnumApi | NullEnumApi | null
    /** @nullable */
    conversations_enabled?: boolean | null
    conversations_settings?: unknown | null
    logs_settings?: unknown | null
    readonly available_setup_task_ids: readonly AvailableSetupTaskIdsEnumApi[]
}

export type PatchedProjectBackwardCompatApiGroupTypesItem = { [key: string]: unknown }

/**
 * Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of
passthrough fields. This allows the meaning of `Team` to change from "project" to "environment" without breaking
backward compatibility of the REST API.
Do not use this in greenfield endpoints!
 */
export interface PatchedProjectBackwardCompatApi {
    readonly id?: number
    readonly organization?: string
    /**
     * @minLength 1
     * @maxLength 200
     */
    name?: string
    /**
     * @maxLength 1000
     * @nullable
     */
    product_description?: string | null
    readonly created_at?: string
    readonly effective_membership_level?: EffectiveMembershipLevelEnumApi | null
    readonly has_group_types?: boolean
    readonly group_types?: readonly PatchedProjectBackwardCompatApiGroupTypesItem[]
    /** @nullable */
    readonly live_events_token?: string | null
    readonly updated_at?: string
    readonly uuid?: string
    readonly api_token?: string
    app_urls?: (string | null)[]
    /**
     * @maxLength 500
     * @nullable
     */
    slack_incoming_webhook?: string | null
    anonymize_ips?: boolean
    completed_snippet_onboarding?: boolean
    readonly ingested_event?: boolean
    test_account_filters?: unknown
    /** @nullable */
    test_account_filters_default_checked?: boolean | null
    path_cleaning_filters?: unknown | null
    is_demo?: boolean
    timezone?: string
    data_attributes?: unknown
    /** @nullable */
    person_display_name_properties?: string[] | null
    correlation_config?: unknown | null
    /** @nullable */
    autocapture_opt_out?: boolean | null
    /** @nullable */
    autocapture_exceptions_opt_in?: boolean | null
    /** @nullable */
    autocapture_web_vitals_opt_in?: boolean | null
    autocapture_web_vitals_allowed_metrics?: unknown | null
    autocapture_exceptions_errors_to_ignore?: unknown | null
    /** @nullable */
    capture_console_log_opt_in?: boolean | null
    /** @nullable */
    capture_performance_opt_in?: boolean | null
    session_recording_opt_in?: boolean
    /**
     * @nullable
     * @pattern ^-?\d{0,1}(?:\.\d{0,2})?$
     */
    session_recording_sample_rate?: string | null
    /**
     * @minimum 0
     * @maximum 30000
     * @nullable
     */
    session_recording_minimum_duration_milliseconds?: number | null
    session_recording_linked_flag?: unknown | null
    session_recording_network_payload_capture_config?: unknown | null
    session_recording_masking_config?: unknown | null
    session_replay_config?: unknown | null
    survey_config?: unknown | null
    access_control?: boolean
    /**
     * @minimum -32768
     * @maximum 32767
     */
    week_start_day?: WeekStartDayEnumApi | NullEnumApi | null
    /** @nullable */
    primary_dashboard?: number | null
    /** @nullable */
    live_events_columns?: string[] | null
    /** @nullable */
    recording_domains?: (string | null)[] | null
    readonly person_on_events_querying_enabled?: string
    /** @nullable */
    inject_web_apps?: boolean | null
    extra_settings?: unknown | null
    modifiers?: unknown | null
    readonly default_modifiers?: string
    has_completed_onboarding_for?: unknown | null
    /** @nullable */
    surveys_opt_in?: boolean | null
    /** @nullable */
    heatmaps_opt_in?: boolean | null
    readonly product_intents?: string
    /** @nullable */
    flags_persistence_default?: boolean | null
    /** @nullable */
    readonly secret_api_token?: string | null
    /** @nullable */
    readonly secret_api_token_backup?: string | null
    /** @nullable */
    receive_org_level_activity_logs?: boolean | null
    /** Whether this project serves B2B or B2C customers, used to optimize the UI layout.

* `b2b` - B2B
* `b2c` - B2C
* `other` - Other */
    business_model?: BusinessModelEnumApi | BlankEnumApi | NullEnumApi | null
    /** @nullable */
    conversations_enabled?: boolean | null
    conversations_settings?: unknown | null
    logs_settings?: unknown | null
    readonly available_setup_task_ids?: readonly AvailableSetupTaskIdsEnumApi[]
}

export interface RoleApi {
    readonly id: string
    /** @maxLength 200 */
    name: string
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly members: string
    readonly is_default: string
}

export interface PaginatedRoleListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: RoleApi[]
}

export interface PatchedRoleApi {
    readonly id?: string
    /** @maxLength 200 */
    name?: string
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    readonly members?: string
    readonly is_default?: string
}

/**
 * * `USR` - user
 * `GIT` - GitHub
 */
export type CreationTypeEnumApi = (typeof CreationTypeEnumApi)[keyof typeof CreationTypeEnumApi]

export const CreationTypeEnumApi = {
    Usr: 'USR',
    Git: 'GIT',
} as const

/**
 * * `dashboard_item` - insight
 * `dashboard` - dashboard
 * `project` - project
 * `organization` - organization
 * `recording` - recording
 */
export type AnnotationScopeEnumApi = (typeof AnnotationScopeEnumApi)[keyof typeof AnnotationScopeEnumApi]

export const AnnotationScopeEnumApi = {
    DashboardItem: 'dashboard_item',
    Dashboard: 'dashboard',
    Project: 'project',
    Organization: 'organization',
    Recording: 'recording',
} as const

export interface AnnotationApi {
    readonly id: number
    /**
     * @maxLength 8192
     * @nullable
     */
    content?: string | null
    /** @nullable */
    date_marker?: string | null
    creation_type?: CreationTypeEnumApi
    /** @nullable */
    dashboard_item?: number | null
    /** @nullable */
    dashboard_id?: number | null
    /** @nullable */
    readonly dashboard_name: string | null
    /** @nullable */
    readonly insight_short_id: string | null
    /** @nullable */
    readonly insight_name: string | null
    /** @nullable */
    readonly insight_derived_name: string | null
    readonly created_by: UserBasicApi
    /** @nullable */
    readonly created_at: string | null
    readonly updated_at: string
    deleted?: boolean
    scope?: AnnotationScopeEnumApi
}

export interface PaginatedAnnotationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: AnnotationApi[]
}

export interface PatchedAnnotationApi {
    readonly id?: number
    /**
     * @maxLength 8192
     * @nullable
     */
    content?: string | null
    /** @nullable */
    date_marker?: string | null
    creation_type?: CreationTypeEnumApi
    /** @nullable */
    dashboard_item?: number | null
    /** @nullable */
    dashboard_id?: number | null
    /** @nullable */
    readonly dashboard_name?: string | null
    /** @nullable */
    readonly insight_short_id?: string | null
    /** @nullable */
    readonly insight_name?: string | null
    /** @nullable */
    readonly insight_derived_name?: string | null
    readonly created_by?: UserBasicApi
    /** @nullable */
    readonly created_at?: string | null
    readonly updated_at?: string
    deleted?: boolean
    scope?: AnnotationScopeEnumApi
}

export interface CommentApi {
    readonly id: string
    readonly created_by: UserBasicApi
    /** @nullable */
    deleted?: boolean | null
    mentions?: number[]
    slug?: string
    /** @nullable */
    content?: string | null
    rich_content?: unknown | null
    readonly version: number
    readonly created_at: string
    /**
     * @maxLength 72
     * @nullable
     */
    item_id?: string | null
    item_context?: unknown | null
    /** @maxLength 79 */
    scope: string
    /** @nullable */
    source_comment?: string | null
}

export interface PaginatedCommentListApi {
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CommentApi[]
}

export interface PatchedCommentApi {
    readonly id?: string
    readonly created_by?: UserBasicApi
    /** @nullable */
    deleted?: boolean | null
    mentions?: number[]
    slug?: string
    /** @nullable */
    content?: string | null
    rich_content?: unknown | null
    readonly version?: number
    readonly created_at?: string
    /**
     * @maxLength 72
     * @nullable
     */
    item_id?: string | null
    item_context?: unknown | null
    /** @maxLength 79 */
    scope?: string
    /** @nullable */
    source_comment?: string | null
}

/**
 * * `team` - Only team
 * `global` - Global
 * `feature_flag` - Feature Flag
 */
export type DashboardTemplateScopeEnumApi =
    (typeof DashboardTemplateScopeEnumApi)[keyof typeof DashboardTemplateScopeEnumApi]

export const DashboardTemplateScopeEnumApi = {
    Team: 'team',
    Global: 'global',
    FeatureFlag: 'feature_flag',
} as const

export interface DashboardTemplateApi {
    readonly id: string
    /**
     * @maxLength 400
     * @nullable
     */
    template_name?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    dashboard_description?: string | null
    dashboard_filters?: unknown | null
    /** @nullable */
    tags?: string[] | null
    tiles?: unknown | null
    variables?: unknown | null
    /** @nullable */
    deleted?: boolean | null
    /** @nullable */
    readonly created_at: string | null
    /** @nullable */
    created_by?: number | null
    /**
     * @maxLength 8201
     * @nullable
     */
    image_url?: string | null
    /** @nullable */
    readonly team_id: number | null
    scope?: DashboardTemplateScopeEnumApi | BlankEnumApi | NullEnumApi | null
    /** @nullable */
    availability_contexts?: string[] | null
}

export interface PaginatedDashboardTemplateListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: DashboardTemplateApi[]
}

export interface PatchedDashboardTemplateApi {
    readonly id?: string
    /**
     * @maxLength 400
     * @nullable
     */
    template_name?: string | null
    /**
     * @maxLength 400
     * @nullable
     */
    dashboard_description?: string | null
    dashboard_filters?: unknown | null
    /** @nullable */
    tags?: string[] | null
    tiles?: unknown | null
    variables?: unknown | null
    /** @nullable */
    deleted?: boolean | null
    /** @nullable */
    readonly created_at?: string | null
    /** @nullable */
    created_by?: number | null
    /**
     * @maxLength 8201
     * @nullable
     */
    image_url?: string | null
    /** @nullable */
    readonly team_id?: number | null
    scope?: DashboardTemplateScopeEnumApi | BlankEnumApi | NullEnumApi | null
    /** @nullable */
    availability_contexts?: string[] | null
}

/**
 * * `allow` - Allow
 * `reject` - Reject
 */
export type EnforcementModeEnumApi = (typeof EnforcementModeEnumApi)[keyof typeof EnforcementModeEnumApi]

export const EnforcementModeEnumApi = {
    Allow: 'allow',
    Reject: 'reject',
} as const

/**
 * Serializer mixin that handles tags for objects.
 */
export interface EnterpriseEventDefinitionApi {
    readonly id: string
    /** @maxLength 400 */
    name: string
    /** @nullable */
    owner?: number | null
    /** @nullable */
    description?: string | null
    tags?: unknown[]
    /** @nullable */
    readonly created_at: string | null
    readonly updated_at: string
    readonly updated_by: UserBasicApi
    /** @nullable */
    readonly last_seen_at: string | null
    readonly last_updated_at: string
    verified?: boolean
    /** @nullable */
    readonly verified_at: string | null
    readonly verified_by: UserBasicApi
    /** @nullable */
    hidden?: boolean | null
    enforcement_mode?: EnforcementModeEnumApi
    readonly is_action: boolean
    readonly action_id: number
    readonly is_calculating: boolean
    readonly last_calculated_at: string
    readonly created_by: UserBasicApi
    post_to_slack?: boolean
    default_columns?: string[]
    readonly media_preview_urls: readonly string[]
}

export interface PaginatedEnterpriseEventDefinitionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: EnterpriseEventDefinitionApi[]
}

/**
 * Serializer mixin that handles tags for objects.
 */
export interface PatchedEnterpriseEventDefinitionApi {
    readonly id?: string
    /** @maxLength 400 */
    name?: string
    /** @nullable */
    owner?: number | null
    /** @nullable */
    description?: string | null
    tags?: unknown[]
    /** @nullable */
    readonly created_at?: string | null
    readonly updated_at?: string
    readonly updated_by?: UserBasicApi
    /** @nullable */
    readonly last_seen_at?: string | null
    readonly last_updated_at?: string
    verified?: boolean
    /** @nullable */
    readonly verified_at?: string | null
    readonly verified_by?: UserBasicApi
    /** @nullable */
    hidden?: boolean | null
    enforcement_mode?: EnforcementModeEnumApi
    readonly is_action?: boolean
    readonly action_id?: number
    readonly is_calculating?: boolean
    readonly last_calculated_at?: string
    readonly created_by?: UserBasicApi
    post_to_slack?: boolean
    default_columns?: string[]
    readonly media_preview_urls?: readonly string[]
}

export type EventDefinitionApiProperties = { [key: string]: unknown }

export interface EventDefinitionApi {
    elements: unknown[]
    event: string
    properties: EventDefinitionApiProperties
}

/**
 * * `image/png` - image/png
 * `application/pdf` - application/pdf
 * `text/csv` - text/csv
 * `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
 * `video/webm` - video/webm
 * `video/mp4` - video/mp4
 * `image/gif` - image/gif
 * `application/json` - application/json
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
    readonly has_content: string
    export_context?: unknown | null
    readonly filename: string
    /** @nullable */
    readonly expires_after: string | null
    /** @nullable */
    readonly exception: string | null
}

export interface PaginatedExportedAssetListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ExportedAssetApi[]
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
    meta?: unknown | null
    /** @nullable */
    shortcut?: boolean | null
    readonly created_at: string
    /** @nullable */
    readonly last_viewed_at: string | null
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
    meta?: unknown | null
    /** @nullable */
    shortcut?: boolean | null
    readonly created_at?: string
    /** @nullable */
    readonly last_viewed_at?: string | null
}

export interface SharingConfigurationApi {
    readonly created_at: string
    enabled?: boolean
    /** @nullable */
    readonly access_token: string | null
    settings?: unknown | null
    password_required?: boolean
    readonly share_passwords: string
}

/**
 * * `slack` - Slack
 * `salesforce` - Salesforce
 * `hubspot` - Hubspot
 * `google-pubsub` - Google Pubsub
 * `google-cloud-storage` - Google Cloud Storage
 * `google-ads` - Google Ads
 * `google-sheets` - Google Sheets
 * `snapchat` - Snapchat
 * `linkedin-ads` - Linkedin Ads
 * `reddit-ads` - Reddit Ads
 * `tiktok-ads` - Tiktok Ads
 * `bing-ads` - Bing Ads
 * `intercom` - Intercom
 * `email` - Email
 * `linear` - Linear
 * `github` - Github
 * `gitlab` - Gitlab
 * `meta-ads` - Meta Ads
 * `twilio` - Twilio
 * `clickup` - Clickup
 * `vercel` - Vercel
 * `databricks` - Databricks
 * `azure-blob` - Azure Blob
 * `firebase` - Firebase
 * `jira` - Jira
 */
export type KindCf2EnumApi = (typeof KindCf2EnumApi)[keyof typeof KindCf2EnumApi]

export const KindCf2EnumApi = {
    Slack: 'slack',
    Salesforce: 'salesforce',
    Hubspot: 'hubspot',
    GooglePubsub: 'google-pubsub',
    GoogleCloudStorage: 'google-cloud-storage',
    GoogleAds: 'google-ads',
    GoogleSheets: 'google-sheets',
    Snapchat: 'snapchat',
    LinkedinAds: 'linkedin-ads',
    RedditAds: 'reddit-ads',
    TiktokAds: 'tiktok-ads',
    BingAds: 'bing-ads',
    Intercom: 'intercom',
    Email: 'email',
    Linear: 'linear',
    Github: 'github',
    Gitlab: 'gitlab',
    MetaAds: 'meta-ads',
    Twilio: 'twilio',
    Clickup: 'clickup',
    Vercel: 'vercel',
    Databricks: 'databricks',
    AzureBlob: 'azure-blob',
    Firebase: 'firebase',
    Jira: 'jira',
} as const

/**
 * Standard Integration serializer.
 */
export interface IntegrationApi {
    readonly id: number
    kind: KindCf2EnumApi
    config?: unknown
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly errors: string
    readonly display_name: string
}

export interface PaginatedIntegrationListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: IntegrationApi[]
}

/**
 * Standard Integration serializer.
 */
export interface PatchedIntegrationApi {
    readonly id?: number
    kind?: KindCf2EnumApi
    config?: unknown
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    readonly errors?: string
    readonly display_name?: string
}

/**
 * * `DateTime` - DateTime
 * `String` - String
 * `Numeric` - Numeric
 * `Boolean` - Boolean
 * `Duration` - Duration
 */
export type PropertyType549EnumApi = (typeof PropertyType549EnumApi)[keyof typeof PropertyType549EnumApi]

export const PropertyType549EnumApi = {
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
    property_type?: PropertyType549EnumApi | BlankEnumApi | NullEnumApi | null
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
    property_type?: PropertyType549EnumApi | BlankEnumApi | NullEnumApi | null
    verified?: boolean
    /** @nullable */
    readonly verified_at?: string | null
    readonly verified_by?: UserBasicApi
    /** @nullable */
    hidden?: boolean | null
}

/**
 * * `FeatureFlag` - feature flag
 */
export type ModelNameEnumApi = (typeof ModelNameEnumApi)[keyof typeof ModelNameEnumApi]

export const ModelNameEnumApi = {
    FeatureFlag: 'FeatureFlag',
} as const

/**
 * * `daily` - daily
 * `weekly` - weekly
 * `monthly` - monthly
 * `yearly` - yearly
 */
export type RecurrenceIntervalEnumApi = (typeof RecurrenceIntervalEnumApi)[keyof typeof RecurrenceIntervalEnumApi]

export const RecurrenceIntervalEnumApi = {
    Daily: 'daily',
    Weekly: 'weekly',
    Monthly: 'monthly',
    Yearly: 'yearly',
} as const

export interface ScheduledChangeApi {
    readonly id: number
    readonly team_id: number
    /** @maxLength 200 */
    record_id: string
    model_name: ModelNameEnumApi
    payload?: unknown
    scheduled_at: string
    /** @nullable */
    executed_at?: string | null
    /**
     * Return the safely formatted failure reason instead of raw data.
     * @nullable
     */
    readonly failure_reason: string | null
    readonly created_at: string
    readonly created_by: UserBasicApi
    readonly updated_at: string
    is_recurring?: boolean
    recurrence_interval?: RecurrenceIntervalEnumApi | BlankEnumApi | NullEnumApi | null
    /** @nullable */
    readonly last_executed_at: string | null
    /** @nullable */
    end_date?: string | null
}

export interface PaginatedScheduledChangeListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: ScheduledChangeApi[]
}

export interface PatchedScheduledChangeApi {
    readonly id?: number
    readonly team_id?: number
    /** @maxLength 200 */
    record_id?: string
    model_name?: ModelNameEnumApi
    payload?: unknown
    scheduled_at?: string
    /** @nullable */
    executed_at?: string | null
    /**
     * Return the safely formatted failure reason instead of raw data.
     * @nullable
     */
    readonly failure_reason?: string | null
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    readonly updated_at?: string
    is_recurring?: boolean
    recurrence_interval?: RecurrenceIntervalEnumApi | BlankEnumApi | NullEnumApi | null
    /** @nullable */
    readonly last_executed_at?: string | null
    /** @nullable */
    end_date?: string | null
}

/**
 * * `email` - Email
 * `slack` - Slack
 * `webhook` - Webhook
 */
export type TargetTypeEnumApi = (typeof TargetTypeEnumApi)[keyof typeof TargetTypeEnumApi]

export const TargetTypeEnumApi = {
    Email: 'email',
    Slack: 'slack',
    Webhook: 'webhook',
} as const

/**
 * * `daily` - Daily
 * `weekly` - Weekly
 * `monthly` - Monthly
 * `yearly` - Yearly
 */
export type FrequencyEnumApi = (typeof FrequencyEnumApi)[keyof typeof FrequencyEnumApi]

export const FrequencyEnumApi = {
    Daily: 'daily',
    Weekly: 'weekly',
    Monthly: 'monthly',
    Yearly: 'yearly',
} as const

/**
 * * `monday` - Monday
 * `tuesday` - Tuesday
 * `wednesday` - Wednesday
 * `thursday` - Thursday
 * `friday` - Friday
 * `saturday` - Saturday
 * `sunday` - Sunday
 */
export type ByweekdayEnumApi = (typeof ByweekdayEnumApi)[keyof typeof ByweekdayEnumApi]

export const ByweekdayEnumApi = {
    Monday: 'monday',
    Tuesday: 'tuesday',
    Wednesday: 'wednesday',
    Thursday: 'thursday',
    Friday: 'friday',
    Saturday: 'saturday',
    Sunday: 'sunday',
} as const

/**
 * Standard Subscription serializer.
 */
export interface SubscriptionApi {
    readonly id: number
    /** @nullable */
    dashboard?: number | null
    /** @nullable */
    insight?: number | null
    target_type: TargetTypeEnumApi
    target_value: string
    frequency: FrequencyEnumApi
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    interval?: number
    /** @nullable */
    byweekday?: ByweekdayEnumApi[] | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    bysetpos?: number | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    count?: number | null
    start_date: string
    /** @nullable */
    until_date?: string | null
    readonly created_at: string
    readonly created_by: UserBasicApi
    deleted?: boolean
    /**
     * @maxLength 100
     * @nullable
     */
    title?: string | null
    readonly summary: string
    /** @nullable */
    readonly next_delivery_date: string | null
    /** @nullable */
    invite_message?: string | null
}

export interface PaginatedSubscriptionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: SubscriptionApi[]
}

/**
 * Standard Subscription serializer.
 */
export interface PatchedSubscriptionApi {
    readonly id?: number
    /** @nullable */
    dashboard?: number | null
    /** @nullable */
    insight?: number | null
    target_type?: TargetTypeEnumApi
    target_value?: string
    frequency?: FrequencyEnumApi
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     */
    interval?: number
    /** @nullable */
    byweekday?: ByweekdayEnumApi[] | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    bysetpos?: number | null
    /**
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    count?: number | null
    start_date?: string
    /** @nullable */
    until_date?: string | null
    readonly created_at?: string
    readonly created_by?: UserBasicApi
    deleted?: boolean
    /**
     * @maxLength 100
     * @nullable
     */
    title?: string | null
    readonly summary?: string
    /** @nullable */
    readonly next_delivery_date?: string | null
    /** @nullable */
    invite_message?: string | null
}

/**
 * * `disabled` - disabled
 * `toolbar` - toolbar
 */
export type ToolbarModeEnumApi = (typeof ToolbarModeEnumApi)[keyof typeof ToolbarModeEnumApi]

export const ToolbarModeEnumApi = {
    Disabled: 'disabled',
    Toolbar: 'toolbar',
} as const

/**
 * Serializer for `Team` model with minimal attributes to speeed up loading and transfer times.
Also used for nested serializers.
 */
export interface TeamBasicApi {
    readonly id: number
    readonly uuid: string
    readonly organization: string
    /**
     * @minimum -9223372036854776000
     * @maximum 9223372036854776000
     */
    readonly project_id: number
    readonly api_token: string
    readonly name: string
    readonly completed_snippet_onboarding: boolean
    readonly has_completed_onboarding_for: unknown | null
    readonly ingested_event: boolean
    readonly is_demo: boolean
    readonly timezone: string
    readonly access_control: boolean
}

export type MembershipLevelEnumApi = (typeof MembershipLevelEnumApi)[keyof typeof MembershipLevelEnumApi]

export const MembershipLevelEnumApi = {
    Number1: 1,
    Number8: 8,
    Number15: 15,
} as const

/**
 * * `0` - none
 * `3` - config
 * `6` - install
 * `9` - root
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
 * `frequentist` - Frequentist
 */
export type DefaultExperimentStatsMethodEnumApi =
    (typeof DefaultExperimentStatsMethodEnumApi)[keyof typeof DefaultExperimentStatsMethodEnumApi]

export const DefaultExperimentStatsMethodEnumApi = {
    Bayesian: 'bayesian',
    Frequentist: 'frequentist',
} as const

export type OrganizationApiTeamsItem = { [key: string]: unknown }

export type OrganizationApiProjectsItem = { [key: string]: unknown }

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
    readonly membership_level: MembershipLevelEnumApi | null
    readonly plugins_access_level: PluginsAccessLevelEnumApi
    readonly teams: readonly OrganizationApiTeamsItem[]
    readonly projects: readonly OrganizationApiProjectsItem[]
    /** @nullable */
    readonly available_product_features: readonly unknown[] | null
    is_member_join_email_enabled?: boolean
    readonly metadata: string
    /** @nullable */
    readonly customer_id: string | null
    /** @nullable */
    enforce_2fa?: boolean | null
    /** @nullable */
    members_can_invite?: boolean | null
    members_can_use_personal_api_keys?: boolean
    allow_publicly_shared_resources?: boolean
    readonly member_count: string
    /** @nullable */
    is_ai_data_processing_approved?: boolean | null
    /** Default statistical method for new experiments in this organization.

* `bayesian` - Bayesian
* `frequentist` - Frequentist */
    default_experiment_stats_method?: DefaultExperimentStatsMethodEnumApi | BlankEnumApi | NullEnumApi | null
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
}

/**
 * Serializer for `Organization` model with minimal attributes to speeed up loading and transfer times.
Also used for nested serializers.
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
    readonly membership_level: MembershipLevelEnumApi | null
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
}

export interface ScenePersonalisationBasicApi {
    /** @maxLength 200 */
    scene: string
    /** @nullable */
    dashboard?: number | null
}

/**
 * * `light` - Light
 * `dark` - Dark
 * `system` - System
 */
export type ThemeModeEnumApi = (typeof ThemeModeEnumApi)[keyof typeof ThemeModeEnumApi]

export const ThemeModeEnumApi = {
    Light: 'light',
    Dark: 'dark',
    System: 'system',
} as const

/**
 * * `above` - Above
 * `below` - Below
 * `hidden` - Hidden
 */
export type ShortcutPositionEnumApi = (typeof ShortcutPositionEnumApi)[keyof typeof ShortcutPositionEnumApi]

export const ShortcutPositionEnumApi = {
    Above: 'above',
    Below: 'below',
    Hidden: 'hidden',
} as const

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
    notification_settings?: UserApiNotificationSettings
    /** @nullable */
    anonymize_data?: boolean | null
    /** @nullable */
    allow_impersonation?: boolean | null
    toolbar_mode?: ToolbarModeEnumApi | BlankEnumApi | NullEnumApi | null
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
    current_password?: string
    events_column_config?: unknown
    readonly is_2fa_enabled: boolean
    readonly has_social_auth: boolean
    readonly has_sso_enforcement: boolean
    has_seen_product_intro_for?: unknown | null
    readonly scene_personalisation: readonly ScenePersonalisationBasicApi[]
    theme_mode?: ThemeModeEnumApi | BlankEnumApi | NullEnumApi | null
    hedgehog_config?: unknown | null
    /** @nullable */
    allow_sidebar_suggestions?: boolean | null
    shortcut_position?: ShortcutPositionEnumApi | BlankEnumApi | NullEnumApi | null
    role_at_organization?: RoleAtOrganizationEnumApi
    /**
     * Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.
     * @nullable
     */
    passkeys_enabled_for_2fa?: boolean | null
}

export interface PaginatedUserListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: UserApi[]
}

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
    notification_settings?: PatchedUserApiNotificationSettings
    /** @nullable */
    anonymize_data?: boolean | null
    /** @nullable */
    allow_impersonation?: boolean | null
    toolbar_mode?: ToolbarModeEnumApi | BlankEnumApi | NullEnumApi | null
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
    current_password?: string
    events_column_config?: unknown
    readonly is_2fa_enabled?: boolean
    readonly has_social_auth?: boolean
    readonly has_sso_enforcement?: boolean
    has_seen_product_intro_for?: unknown | null
    readonly scene_personalisation?: readonly ScenePersonalisationBasicApi[]
    theme_mode?: ThemeModeEnumApi | BlankEnumApi | NullEnumApi | null
    hedgehog_config?: unknown | null
    /** @nullable */
    allow_sidebar_suggestions?: boolean | null
    shortcut_position?: ShortcutPositionEnumApi | BlankEnumApi | NullEnumApi | null
    role_at_organization?: RoleAtOrganizationEnumApi
    /**
     * Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.
     * @nullable
     */
    passkeys_enabled_for_2fa?: boolean | null
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

export type MembersListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type List2Params = {
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

export type RolesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type AnnotationsListParams = {
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

export type CommentsListParams = {
    /**
     * The pagination cursor value.
     */
    cursor?: string
}

export type DashboardTemplatesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type EventDefinitionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type EventDefinitionsByNameRetrieveParams = {
    /**
     * The exact event name to look up
     */
    name: string
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

export type FlagValueValuesRetrieveParams = {
    /**
     * The flag ID
     */
    key?: string
}

export type FlagValueValuesRetrieve200Item = { [key: string]: unknown }

/**
 * Unspecified response body
 */
export type FlagValueValuesRetrieve400 = { [key: string]: unknown }

/**
 * Unspecified response body
 */
export type FlagValueValuesRetrieve404 = { [key: string]: unknown }

export type IntegrationsList2Params = {
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
     * JSON-encoded list of excluded properties
     * @minLength 1
     */
    excluded_properties?: string
    /**
     * Whether to return only properties for events in `event_names`
     * @nullable
     */
    filter_by_event_names?: boolean | null
    /**
     * What group type is the property for. Only should be set if `type=group`
     */
    group_type_index?: number
    /**
     * Whether to return only (or excluding) feature flag properties
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

* `event` - event
* `person` - person
* `group` - group
* `session` - session
 * @minLength 1
 */
    type?: PropertyDefinitionsListType
}

export type PropertyDefinitionsListType = (typeof PropertyDefinitionsListType)[keyof typeof PropertyDefinitionsListType]

export const PropertyDefinitionsListType = {
    Event: 'event',
    Person: 'person',
    Group: 'group',
    Session: 'session',
} as const

export type ScheduledChangesListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type SubscriptionsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

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
