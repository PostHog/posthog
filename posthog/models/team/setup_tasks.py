from enum import StrEnum


class SetupTaskId(StrEnum):
    # Global tasks (apply to all products)
    IngestFirstEvent = "ingest_first_event"
    SetUpReverseProxy = "set_up_reverse_proxy"

    # Product Analytics
    CreateFirstInsight = "create_first_insight"
    CreateFirstDashboard = "create_first_dashboard"
    TrackCustomEvents = "track_custom_events"
    DefineActions = "define_actions"
    SetUpCohorts = "set_up_cohorts"
    ExploreTrendsInsight = "explore_trends_insight"
    ExploreFunnelInsight = "create_funnel"
    ExploreRetentionInsight = "explore_retention_insight"
    ExplorePathsInsight = "explore_paths_insight"
    ExploreStickinessInsight = "explore_stickiness_insight"
    ExploreLifecycleInsight = "explore_lifecycle_insight"

    # Web Analytics
    AddAuthorizedDomain = "add_authorized_domain"
    SetUpWebVitals = "set_up_web_vitals"
    ReviewWebAnalyticsDashboard = "review_web_analytics_dashboard"
    FilterWebAnalytics = "filter_web_analytics"
    SetUpWebAnalyticsConversionGoals = "set_up_web_analytics_conversion_goals"
    VisitWebVitalsDashboard = "visit_web_vitals_dashboard"

    # Session Replay
    SetupSessionRecordings = "setup_session_recordings"
    WatchSessionRecording = "watch_session_recording"
    ConfigureRecordingSettings = "configure_recording_settings"
    CreateRecordingPlaylist = "create_recording_playlist"
    EnableConsoleLogs = "enable_console_logs"

    # Feature Flags
    CreateFeatureFlag = "create_feature_flag"
    ImplementFlagInCode = "implement_flag_in_code"
    UpdateFeatureFlagReleaseConditions = "update_feature_flag_release_conditions"
    CreateMultivariateFlag = "create_multivariate_flag"
    SetUpFlagPayloads = "set_up_flag_payloads"
    SetUpFlagEvaluationRuntimes = "set_up_flag_evaluation_runtimes"

    # Experiments
    CreateExperiment = "create_experiment"
    ImplementExperimentVariants = "implement_experiment_variants"
    LaunchExperiment = "launch_experiment"
    ReviewExperimentResults = "review_experiment_results"

    # Surveys
    CreateSurvey = "create_survey"
    LaunchSurvey = "launch_survey"
    CollectSurveyResponses = "collect_survey_responses"

    # Data Warehouse
    ConnectFirstSource = "connect_source"
    RunFirstQuery = "run_first_query"
    JoinExternalData = "join_external_data"
    CreateSavedView = "create_saved_view"

    # Error Tracking
    EnableErrorTracking = "enable_error_tracking"
    UploadSourceMaps = "upload_source_maps"
    ViewFirstError = "view_first_error"
    ResolveFirstError = "resolve_first_error"

    # LLM Analytics
    IngestFirstLlmEvent = "ingest_first_llm_event"
    ViewFirstTrace = "view_first_trace"
    TrackCosts = "track_costs"
    SetUpLlmEvaluation = "set_up_llm_evaluation"
    RunAIPlayground = "run_ai_playground"

    # Revenue Analytics
    EnableRevenueAnalyticsViewset = "enable_revenue_analytics_viewset"
    ConnectRevenueSource = "connect_revenue_source"
    SetUpRevenueGoal = "set_up_revenue_goal"

    # Logs
    EnableLogCapture = "enable_log_capture"
    ViewFirstLogs = "view_first_logs"

    # Workflows
    CreateFirstWorkflow = "create_first_workflow"
    SetUpFirstWorkflowChannel = "set_up_first_workflow_channel"
    ConfigureWorkflowTrigger = "configure_workflow_trigger"
    AddWorkflowAction = "add_workflow_action"
    LaunchWorkflow = "launch_workflow"

    # Endpoints
    CreateFirstEndpoint = "create_first_endpoint"
    ConfigureEndpoint = "configure_endpoint"
    TestEndpoint = "test_endpoint"

    # Early Access Features
    CreateEarlyAccessFeature = "create_early_access_feature"
    UpdateFeatureStage = "update_feature_stage"
