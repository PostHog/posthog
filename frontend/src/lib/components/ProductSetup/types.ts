import type { ReactNode } from 'react'

import type { ProductKey } from '~/queries/schema/schema-general'

/**
 * All known setup/onboarding task IDs across all products.
 * Using an enum ensures type safety and makes migration easier.
 */
export enum SetupTaskId {
    // Global tasks (apply to all products)
    IngestFirstEvent = 'ingest_first_event',
    SetUpReverseProxy = 'set_up_reverse_proxy',

    // Product Analytics
    CreateFirstInsight = 'create_first_insight',
    CreateFirstDashboard = 'create_first_dashboard',
    TrackCustomEvents = 'track_custom_events',
    DefineActions = 'define_actions',
    SetUpCohorts = 'set_up_cohorts',
    ExploreTrendsInsight = 'explore_trends_insight',
    ExploreFunnelInsight = 'create_funnel', // Keep different name for backwards compatibility
    ExploreRetentionInsight = 'explore_retention_insight',
    ExplorePathsInsight = 'explore_paths_insight',
    ExploreStickinessInsight = 'explore_stickiness_insight',
    ExploreLifecycleInsight = 'explore_lifecycle_insight',

    // Web Analytics
    AddAuthorizedDomain = 'add_authorized_domain',
    SetUpWebVitals = 'set_up_web_vitals',
    ReviewWebAnalyticsDashboard = 'review_web_analytics_dashboard',
    FilterWebAnalytics = 'filter_web_analytics',
    SetUpWebAnalyticsConversionGoals = 'set_up_web_analytics_conversion_goals',
    VisitWebVitalsDashboard = 'visit_web_vitals_dashboard',

    // Session Replay
    SetupSessionRecordings = 'setup_session_recordings',
    WatchSessionRecording = 'watch_session_recording',
    ConfigureRecordingSettings = 'configure_recording_settings',
    CreateRecordingPlaylist = 'create_recording_playlist',
    EnableConsoleLogs = 'enable_console_logs',

    // Feature Flags
    CreateFeatureFlag = 'create_feature_flag',
    ImplementFlagInCode = 'implement_flag_in_code',
    UpdateFeatureFlagReleaseConditions = 'update_feature_flag_release_conditions',
    CreateMultivariateFlag = 'create_multivariate_flag',
    SetUpFlagPayloads = 'set_up_flag_payloads',
    SetUpFlagEvaluationRuntimes = 'set_up_flag_evaluation_runtimes',

    // Experiments
    CreateExperiment = 'create_experiment',
    ImplementExperimentVariants = 'implement_experiment_variants',
    LaunchExperiment = 'launch_experiment',
    ReviewExperimentResults = 'review_experiment_results',

    // Surveys
    CreateSurvey = 'create_survey',
    LaunchSurvey = 'launch_survey',
    CollectSurveyResponses = 'collect_survey_responses',

    // Data Warehouse
    ConnectFirstSource = 'connect_source',
    RunFirstQuery = 'run_first_query',
    JoinExternalData = 'join_external_data',
    CreateSavedView = 'create_saved_view',

    // Error Tracking
    EnableErrorTracking = 'enable_error_tracking',
    UploadSourceMaps = 'upload_source_maps',
    ViewFirstError = 'view_first_error',
    ResolveFirstError = 'resolve_first_error',

    // LLM Analytics
    IngestFirstLlmEvent = 'ingest_first_llm_event',
    ViewFirstTrace = 'view_first_trace',
    TrackCosts = 'track_costs',
    SetUpLlmEvaluation = 'set_up_llm_evaluation',
    RunAIPlayground = 'run_ai_playground',

    // Revenue Analytics
    EnableRevenueAnalyticsViewset = 'enable_revenue_analytics_viewset',
    ConnectRevenueSource = 'connect_revenue_source',
    SetUpRevenueGoal = 'set_up_revenue_goal',

    // Logs
    EnableLogCapture = 'enable_log_capture',
    ViewFirstLogs = 'view_first_logs',
    SetUpLogAlerts = 'set_up_log_alerts',

    // Workflows
    CreateFirstWorkflow = 'create_first_workflow',
    ConfigureWorkflowTrigger = 'configure_workflow_trigger',
    AddWorkflowAction = 'add_workflow_action',
    LaunchWorkflow = 'launch_workflow',

    // Endpoints
    CreateFirstEndpoint = 'create_first_endpoint',
    ConfigureEndpoint = 'configure_endpoint',
    TestEndpoint = 'test_endpoint',

    // Early Access Features
    CreateEarlyAccessFeature = 'create_early_access_feature',
    UpdateFeatureStage = 'update_feature_stage',
}

/**
 * Type of task - determines when/where it appears:
 * - setup: Mandatory configuration tasks that everyone needs to do once
 *   Examples: Install SDK, enable recordings, configure domains
 * - onboarding: Guidance for getting started when product is empty
 *   Examples: Create first insight, watch first recording, create first survey
 * - explore: Advanced/optional features to try after getting started
 *   Examples: Create funnel, set up cohorts, create multivariate flag
 */
export type TaskType = 'setup' | 'onboarding' | 'explore'

/** Definition of a single setup task */
export interface SetupTask {
    /** Unique task identifier - use SetupTaskId enum values */
    id: SetupTaskId
    /** Display title */
    title: string
    /** Help text or description */
    description: string | ReactNode
    /**
     * Warning message to show when user tries to skip this task.
     * If set, a confirmation dialog will be shown before skipping.
     * Tasks without this can be skipped without warning.
     */
    skipWarning?: string
    /**
     * Task type:
     * - 'setup': Mandatory configuration (install SDK, enable features)
     * - 'onboarding': Getting started guidance (create first X, explore Y)
     * Defaults to 'onboarding' if not specified
     */
    taskType?: TaskType
    /** Task IDs that must complete first - use SetupTaskId enum values */
    dependsOn?: SetupTaskId[]
    /** External documentation URL (opens in new tab) */
    docsUrl?: string
    /** Icon for the task */
    icon?: ReactNode
    /** Function that returns the internal URL to navigate to when task is clicked */
    getUrl?: () => string
    /**
     * CSS selector for the element to highlight after navigation.
     * Used to draw attention to the relevant UI element when user runs the task.
     */
    targetSelector?: string
    /**
     * Whether this task requires manual completion by the user.
     * Manual tasks show a checkbox icon and can be marked complete/incomplete by the user.
     * Non-manual tasks are auto-completed by tracking user actions.
     */
    requiresManualCompletion?: boolean
}

/** Runtime state of a setup task (definition + current state) */
export interface SetupTaskWithState extends SetupTask {
    /** Whether task is completed */
    completed: boolean
    /** Whether task was skipped */
    skipped: boolean
    /** If locked, the reason why */
    lockedReason?: string
}

/** Configuration for a product's setup experience */
export interface ProductSetupConfig {
    /** The product key this config is for */
    productKey: ProductKey
    /** Display title, e.g., "Get started with Product analytics" */
    title: string
    /**
     * All tasks for this product, organized by type.
     * Use taskType field to categorize: 'setup', 'onboarding', or 'explore'
     */
    tasks: SetupTask[]
}
