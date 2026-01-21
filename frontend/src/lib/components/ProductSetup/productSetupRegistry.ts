import { OutputTab } from 'scenes/data-warehouse/editor/outputPaneLogic'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { InsightType, OnboardingStepKey, ReplayTabs } from '~/types'

import { type ProductSetupConfig, type SetupTask, SetupTaskId } from './types'

// ============================================================================
// Shared Tasks - reusable across products
// ============================================================================

/** Ingest first event task - include in products that need event data */
export const INGEST_FIRST_EVENT = (productKey: ProductKey): SetupTask => ({
    id: SetupTaskId.IngestFirstEvent,
    title: 'Ingest your first event',
    description: 'Get data flowing into PostHog by installing our SDK or connecting a data source.',
    buttonText: 'Install PostHog',
    skipWarning: "Without events, your dashboards will be empty and you won't be able to explore PostHog.",
    taskType: 'setup',
    requiresManualCompletion: true,
    getUrl: () => urls.onboarding({ productKey, stepKey: OnboardingStepKey.INSTALL }),
    targetSelector: '[data-attr="menu-item-activity"]',
})

/** Set up reverse proxy task - improves data accuracy */
export const SET_UP_REVERSE_PROXY: SetupTask = {
    id: SetupTaskId.SetUpReverseProxy,
    title: 'Set up a reverse proxy',
    description: 'Improve data accuracy by routing PostHog through your own domain.',
    buttonText: 'Set up proxy',
    skipWarning: 'Without a reverse proxy, you might experience data loss from adblockers.',
    taskType: 'setup',
    getUrl: () => urls.settings('organization-proxy'),
}

// ============================================================================
// Product Setup Registry
// ============================================================================

export const PRODUCT_SETUP_REGISTRY: Partial<Record<ProductKey, ProductSetupConfig>> = {
    [ProductKey.PRODUCT_ANALYTICS]: {
        productKey: ProductKey.PRODUCT_ANALYTICS,
        title: 'Get started with Product analytics',
        tasks: [
            INGEST_FIRST_EVENT(ProductKey.PRODUCT_ANALYTICS),
            SET_UP_REVERSE_PROXY,
            {
                id: SetupTaskId.CreateFirstInsight,
                title: 'Create your first insight',
                description: 'Build a trend chart to analyze user behavior over time.',
                buttonText: 'Create insight',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.IngestFirstEvent],
                getUrl: () => urls.insightNew({ type: InsightType.TRENDS }),
            },
            {
                id: SetupTaskId.CreateFunnel,
                title: 'Create a funnel insight',
                description: 'Track how users move through steps like signup → activation → purchase.',
                buttonText: 'Create funnel',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.IngestFirstEvent],
                getUrl: () => urls.insightNew({ type: InsightType.FUNNELS }),
            },
            {
                id: SetupTaskId.CreateFirstDashboard,
                title: 'Create your first dashboard',
                description: 'Combine multiple insights into a dashboard to monitor key metrics.',
                buttonText: 'Create dashboard',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.CreateFirstInsight],
                getUrl: () => urls.dashboards(),
                targetSelector: '[data-attr="new-dashboard"]',
            },
            {
                id: SetupTaskId.TrackCustomEvents,
                title: 'Track custom events',
                description: 'Go beyond autocapture by tracking specific actions that matter.',
                buttonText: 'Learn how',
                taskType: 'explore',
                requiresManualCompletion: true,
                docsUrl: 'https://posthog.com/tutorials/event-tracking-guide#setting-up-custom-events',
                targetSelector: '[data-attr="help-button"]',
            },
            {
                id: SetupTaskId.DefineActions,
                title: 'Define actions',
                description: 'Group related events into actions for easier analysis.',
                buttonText: 'Create action',
                taskType: 'explore',
                dependsOn: [SetupTaskId.IngestFirstEvent],
                getUrl: () => urls.createAction(),
                targetSelector: '[data-attr="create-action"]',
            },
            {
                id: SetupTaskId.SetUpCohorts,
                title: 'Create a user cohort',
                description: 'Group users based on behavior or properties for targeted analysis.',
                buttonText: 'Create cohort',
                taskType: 'explore',
                dependsOn: [SetupTaskId.IngestFirstEvent],
                getUrl: () => urls.cohort('new'),
                targetSelector: '[data-attr="new-cohort"]',
            },
        ],
    },

    [ProductKey.WEB_ANALYTICS]: {
        productKey: ProductKey.WEB_ANALYTICS,
        title: 'Get started with Web analytics',
        tasks: [
            INGEST_FIRST_EVENT(ProductKey.WEB_ANALYTICS),
            {
                id: SetupTaskId.AddAuthorizedDomain,
                title: 'Add your domain',
                description: 'Authorize your website domain to enable accurate traffic tracking.',
                buttonText: 'Add domain',
                skipWarning: "Without a domain, you can't use the toolbar or categorize traffic properly.",
                taskType: 'setup',
                getUrl: () => urls.settings('environment', 'web-analytics-authorized-urls'),
                targetSelector: '[data-attr="authorized-urls-table"]',
            },
            {
                id: SetupTaskId.SetUpWebVitals,
                title: 'Enable web vitals',
                description: 'Track Core Web Vitals (LCP, FID, CLS) to monitor site performance.',
                buttonText: 'Enable vitals',
                taskType: 'setup',
                getUrl: () => urls.settings('environment-autocapture', 'web-vitals-autocapture'),
                targetSelector: '#posthog-autocapture-web-vitals-switch',
            },
            {
                id: SetupTaskId.ReviewWebAnalyticsDashboard,
                title: 'Review your dashboard',
                description: 'Explore pageviews, sessions, and user sources.',
                buttonText: 'View dashboard',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.IngestFirstEvent],
                getUrl: () => urls.webAnalytics(),
                targetSelector: '[data-attr="web-analytics-dashboard"]',
            },
            {
                id: SetupTaskId.FilterWebAnalytics,
                title: 'Filter your analytics',
                description: 'Filter data to focus on what matters to you.',
                buttonText: 'Filter data',
                taskType: 'explore',
                getUrl: () => urls.webAnalytics(),
                targetSelector: '[data-attr="web-analytics-filters"]',
            },
            {
                id: SetupTaskId.SetUpWebAnalyticsConversionGoals,
                title: 'Set up conversion goals',
                description: 'Track important conversions like signups or purchases.',
                buttonText: 'Set up goals',
                taskType: 'explore',
                getUrl: () => urls.webAnalytics(),
                targetSelector: '[data-attr="web-analytics-conversion-filter"]',
            },

            {
                id: SetupTaskId.VisitWebVitalsDashboard,
                title: 'Visit your web vitals dashboard',
                description: 'Monitor your site performance over time.',
                buttonText: 'Visit dashboard',
                taskType: 'explore',
                getUrl: () => urls.webAnalyticsWebVitals(),
            },
        ],
    },

    [ProductKey.SESSION_REPLAY]: {
        productKey: ProductKey.SESSION_REPLAY,
        title: 'Get started with Session replay',
        tasks: [
            INGEST_FIRST_EVENT(ProductKey.SESSION_REPLAY),
            SET_UP_REVERSE_PROXY,
            {
                id: SetupTaskId.SetupSessionRecordings,
                title: 'Enable session recordings',
                description: 'Turn on recording to capture user interactions.',
                buttonText: 'Enable recordings',
                skipWarning: 'Without recordings enabled, you cannot use session replay.',
                taskType: 'setup',
                getUrl: () => urls.replaySettings('replay'),
                targetSelector: '[data-attr="settings-menu-item-replay"]',
            },
            {
                id: SetupTaskId.ConfigureRecordingSettings,
                title: 'Configure recording settings',
                description: 'Customize sampling rate, privacy masking, and network capture.',
                buttonText: 'Configure',
                taskType: 'setup',
                dependsOn: [SetupTaskId.SetupSessionRecordings],
                getUrl: () => urls.replaySettings('replay-triggers'),
                targetSelector: '[data-attr="settings-menu-item-replay-triggers"]',
            },
            {
                id: SetupTaskId.EnableConsoleLogs,
                title: 'Enable console log capture',
                description: 'See JavaScript console logs alongside recordings for debugging.',
                buttonText: 'Enable logs',
                taskType: 'setup',
                dependsOn: [SetupTaskId.SetupSessionRecordings],
                getUrl: () => urls.replaySettings('replay-network'),
                targetSelector: '[data-attr="settings-menu-item-replay-network"]',
            },
            {
                id: SetupTaskId.WatchSessionRecording,
                title: 'Watch your first recording',
                description: 'See exactly how a real user interacted with your product.',
                buttonText: 'Watch recording',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.SetupSessionRecordings],
                getUrl: () => urls.replay(ReplayTabs.Home),
                targetSelector: '[data-attr="session-recordings-playlist"]',
            },
            {
                id: SetupTaskId.CreateRecordingPlaylist,
                title: 'Create a recording playlist',
                description: 'Save filtered recordings for specific user journeys or issues.',
                buttonText: 'Create playlist',
                taskType: 'explore',
                dependsOn: [SetupTaskId.SetupSessionRecordings],
                getUrl: () => urls.replay(ReplayTabs.Playlists),
                targetSelector: '[data-attr="save-recordings-playlist-button"]',
            },
        ],
    },

    [ProductKey.FEATURE_FLAGS]: {
        productKey: ProductKey.FEATURE_FLAGS,
        title: 'Get started with Feature flags',
        tasks: [
            INGEST_FIRST_EVENT(ProductKey.FEATURE_FLAGS),
            SET_UP_REVERSE_PROXY,
            {
                id: SetupTaskId.CreateFeatureFlag,
                title: 'Create your first feature flag',
                description: 'Create a flag to control feature rollouts without deploying.',
                buttonText: 'Create flag',
                taskType: 'onboarding',
                getUrl: () => urls.featureFlag('new'),
                targetSelector: '[data-attr="new-feature-flag"]',
            },
            {
                id: SetupTaskId.ImplementFlagInCode,
                title: 'Implement flag in your code',
                description: 'Add the feature flag check to your application.',
                buttonText: 'View code',
                taskType: 'onboarding',
                requiresManualCompletion: true,
                dependsOn: [SetupTaskId.CreateFeatureFlag],
                docsUrl: 'https://posthog.com/docs/feature-flags/installation',
                targetSelector: '[data-attr="help-button"]',
            },
            {
                id: SetupTaskId.UpdateFeatureFlagReleaseConditions,
                title: 'Configure release conditions',
                description: 'Target specific users or percentages with your flag.',
                buttonText: 'Edit conditions',
                taskType: 'explore',
                dependsOn: [SetupTaskId.CreateFeatureFlag],
                getUrl: () => urls.featureFlags(),
                targetSelector: '[data-attr="feature-flag-table"]',
            },
            {
                id: SetupTaskId.CreateMultivariateFlag,
                title: 'Create a multivariate flag',
                description: 'Test multiple variants with different user groups.',
                buttonText: 'Create flag',
                taskType: 'explore',
                dependsOn: [SetupTaskId.CreateFeatureFlag],
                getUrl: () => urls.featureFlag('new'),
                targetSelector: '[data-attr="new-feature-flag"]',
            },
            {
                id: SetupTaskId.SetUpFlagPayloads,
                title: 'Use flag payloads',
                description: 'Pass dynamic configuration to your feature flags.',
                buttonText: 'Learn more',
                taskType: 'explore',
                docsUrl: 'https://posthog.com/docs/feature-flags/payloads',
                targetSelector: '[data-attr="help-button"]',
            },
        ],
    },

    [ProductKey.EXPERIMENTS]: {
        productKey: ProductKey.EXPERIMENTS,
        title: 'Get started with Experiments',
        tasks: [
            INGEST_FIRST_EVENT(ProductKey.EXPERIMENTS),
            SET_UP_REVERSE_PROXY,
            {
                id: SetupTaskId.CreateExperiment,
                title: 'Create your first experiment',
                description: 'Set up an A/B test to measure the impact of a change.',
                buttonText: 'Create experiment',
                taskType: 'onboarding',
                getUrl: () => urls.experiment('new'),
                targetSelector: '[data-attr="create-experiment"]',
            },
            {
                id: SetupTaskId.DefineExperimentGoal,
                title: 'Define your experiment goal',
                description: 'Choose the metric you want to improve.',
                buttonText: 'Set goal',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.CreateExperiment],
                getUrl: () => urls.experiments(),
                targetSelector: '[data-attr="experiment-creation-goal-metric"]',
            },
            {
                id: SetupTaskId.ImplementExperimentVariants,
                title: 'Implement experiment variants',
                description: 'Add code to show different variants to users.',
                buttonText: 'View code',
                taskType: 'onboarding',
                requiresManualCompletion: true,
                dependsOn: [SetupTaskId.CreateExperiment],
                docsUrl: 'https://posthog.com/docs/experiments/installation',
                targetSelector: '[data-attr="help-button"]',
            },
            {
                id: SetupTaskId.LaunchExperiment,
                title: 'Launch your experiment',
                description: 'Start collecting data by launching your experiment.',
                buttonText: 'Launch',
                taskType: 'explore',
                dependsOn: [SetupTaskId.ImplementExperimentVariants],
                getUrl: () => urls.experiments(),
                targetSelector: '[data-attr="experiment-status"]',
            },
            {
                id: SetupTaskId.ReviewExperimentResults,
                title: 'Review experiment results',
                description: 'Analyze the statistical significance and impact.',
                buttonText: 'View results',
                taskType: 'explore',
                dependsOn: [SetupTaskId.LaunchExperiment],
                getUrl: () => urls.experiments(),
                targetSelector: '[data-attr="experiment-results"]',
            },
        ],
    },

    [ProductKey.SURVEYS]: {
        productKey: ProductKey.SURVEYS,
        title: 'Get started with Surveys',
        tasks: [
            INGEST_FIRST_EVENT(ProductKey.SURVEYS),
            {
                id: SetupTaskId.CreateSurvey,
                title: 'Create your first survey',
                description: 'Choose from templates or build a custom survey.',
                buttonText: 'Create survey',
                taskType: 'onboarding',
                getUrl: () => urls.surveyTemplates(),
                targetSelector: '[data-attr="new-survey"]',
            },
            {
                id: SetupTaskId.LaunchSurvey,
                title: 'Launch your survey',
                description: 'Make your survey live and start collecting responses.',
                buttonText: 'Launch survey',
                taskType: 'explore',
                dependsOn: [SetupTaskId.CreateSurvey],
                getUrl: () => urls.surveys(),
                targetSelector: '[data-attr="launch-survey"]',
            },
        ],
    },

    [ProductKey.DATA_WAREHOUSE]: {
        productKey: ProductKey.DATA_WAREHOUSE,
        title: 'Get started with Data warehouse',
        tasks: [
            {
                id: SetupTaskId.ConnectFirstSource,
                title: 'Connect your first data source',
                description: 'Import data from Stripe, Hubspot, Postgres, or other sources.',
                buttonText: 'Connect source',
                skipWarning: "Without a data source, you can't query data in the warehouse.",
                taskType: 'setup',
                getUrl: () => urls.dataWarehouseSourceNew(),
                targetSelector: '[data-attr="new-source-button"]',
            },
            {
                id: SetupTaskId.RunFirstQuery,
                title: 'Run your first SQL query',
                description: 'Query your data using SQL in the data warehouse.',
                buttonText: 'Open SQL editor',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.ConnectFirstSource],
                getUrl: () => urls.sqlEditor(),
                targetSelector: '[data-attr="sql-editor-button"]',
            },
            {
                id: SetupTaskId.JoinExternalData,
                title: 'Join external data with events',
                description: 'Combine PostHog events with external data.',
                buttonText: 'Create join',
                taskType: 'explore',
                dependsOn: [SetupTaskId.RunFirstQuery],
                getUrl: () => urls.sqlEditor(),
                targetSelector: '[data-attr="sql-editor-button"]',
            },
            {
                id: SetupTaskId.CreateSavedView,
                title: 'Save a view for reuse',
                description: 'Create a saved view from a query to use in insights.',
                buttonText: 'Create view',
                taskType: 'explore',
                dependsOn: [SetupTaskId.RunFirstQuery],
                getUrl: () => urls.sqlEditor(),
                targetSelector: '[data-attr="sql-editor-save-view-button"]',
            },
        ],
    },

    [ProductKey.ERROR_TRACKING]: {
        productKey: ProductKey.ERROR_TRACKING,
        title: 'Get started with Error tracking',
        tasks: [
            INGEST_FIRST_EVENT(ProductKey.ERROR_TRACKING),
            SET_UP_REVERSE_PROXY,
            {
                id: SetupTaskId.EnableErrorTracking,
                title: 'Enable error tracking',
                description: 'Start capturing exceptions and errors from your app.',
                buttonText: 'Enable',
                skipWarning: "Error tracking isn't enabled by default.",
                taskType: 'setup',
                requiresManualCompletion: true,
                getUrl: () =>
                    urls.onboarding({ productKey: ProductKey.ERROR_TRACKING, stepKey: OnboardingStepKey.INSTALL }),
                targetSelector: '[data-attr="menu-item-error_tracking"]',
            },
            {
                id: SetupTaskId.UploadSourceMaps,
                title: 'Upload source maps',
                description: 'See readable stack traces instead of minified code.',
                buttonText: 'Upload maps',
                skipWarning: "Without source maps, stack traces won't be readable.",
                taskType: 'setup',
                requiresManualCompletion: true,
                dependsOn: [SetupTaskId.EnableErrorTracking],
                docsUrl: 'https://posthog.com/docs/error-tracking/source-maps',
                targetSelector: '[data-attr="help-button"]',
            },
            {
                id: SetupTaskId.ViewFirstError,
                title: 'View your first error',
                description: 'Explore error details including stack trace and user context.',
                buttonText: 'View errors',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.EnableErrorTracking],
                getUrl: () => urls.errorTracking(),
                targetSelector: '[data-attr="error-tracking-issue-row"]',
            },
            {
                id: SetupTaskId.ResolveFirstError,
                title: 'Resolve an error',
                description: 'Mark an error as resolved to track your fix rate.',
                buttonText: 'View errors',
                taskType: 'explore',
                dependsOn: [SetupTaskId.ViewFirstError],
                getUrl: () => urls.errorTracking(),
                targetSelector: '[data-attr="error-tracking-resolve"]',
            },
        ],
    },

    [ProductKey.LLM_ANALYTICS]: {
        productKey: ProductKey.LLM_ANALYTICS,
        title: 'Get started with LLM analytics',
        tasks: [
            {
                id: SetupTaskId.IngestFirstLlmEvent,
                title: 'Send your first LLM event',
                description: 'Install the PostHog LLM SDK to start tracking AI usage.',
                buttonText: 'Install SDK',
                skipWarning: "Without LLM events, you can't track AI model usage.",
                taskType: 'setup',
                getUrl: () =>
                    urls.onboarding({ productKey: ProductKey.LLM_ANALYTICS, stepKey: OnboardingStepKey.INSTALL }),
                targetSelector: '[data-attr="menu-item-llm_analytics"]',
            },
            {
                id: SetupTaskId.ViewFirstTrace,
                title: 'View your first trace',
                description: 'See a complete LLM request trace with prompts and latency.',
                buttonText: 'View traces',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.IngestFirstEvent],
                getUrl: () => urls.llmAnalyticsTraces(),
                targetSelector: '[data-attr="llm-trace-table"]',
            },
            {
                id: SetupTaskId.TrackCosts,
                title: 'Track LLM costs',
                description: 'Monitor AI spending by model and use case.',
                buttonText: 'View costs',
                taskType: 'explore',
                dependsOn: [SetupTaskId.IngestFirstEvent],
                getUrl: () => urls.llmAnalyticsDashboard(),
                targetSelector: '[data-attr="llm-analytics-costs"]',
            },
            {
                id: SetupTaskId.SetUpLlmEvaluation,
                title: 'Set up LLM evaluation',
                description: 'Score and evaluate LLM outputs for quality.',
                buttonText: 'Learn more',
                taskType: 'explore',
                docsUrl: 'https://posthog.com/docs/llm-analytics/evaluation',
                targetSelector: '[data-attr="help-button"]',
            },
        ],
    },

    [ProductKey.REVENUE_ANALYTICS]: {
        productKey: ProductKey.REVENUE_ANALYTICS,
        title: 'Get started with Revenue analytics',
        tasks: [
            {
                id: SetupTaskId.ConnectRevenueSource,
                title: 'Connect a revenue source',
                description: 'Import revenue data from Stripe or another provider.',
                buttonText: 'Connect source',
                skipWarning: 'You need a revenue source to view revenue analytics.',
                taskType: 'setup',
                getUrl: () => urls.dataWarehouseSourceNew(),
                targetSelector: '[data-attr="new-source-button"]',
            },
            {
                id: SetupTaskId.SetUpRevenueGoal,
                title: 'Set up a revenue goal',
                description: 'Track progress towards your MRR or revenue targets.',
                buttonText: 'Add goal',
                taskType: 'explore',
                dependsOn: [SetupTaskId.ConnectRevenueSource],
                getUrl: () => urls.revenueSettings(),
                targetSelector: '[data-attr="revenue-analytics-goals"]',
            },
        ],
    },

    [ProductKey.LOGS]: {
        productKey: ProductKey.LOGS,
        title: 'Get started with Logs',
        tasks: [
            {
                id: SetupTaskId.EnableLogCapture,
                title: 'Enable log capture',
                description: 'Start sending logs from your application to PostHog.',
                buttonText: 'Learn how',
                taskType: 'setup',
                requiresManualCompletion: true,
                docsUrl: 'https://posthog.com/docs/logs',
                targetSelector: '[data-attr="help-button"]',
            },
            {
                id: SetupTaskId.ViewFirstLogs,
                title: 'View your logs',
                description: 'Explore application logs with filtering and search.',
                buttonText: 'View logs',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.EnableLogCapture],
                getUrl: () => urls.logs(),
                targetSelector: '[data-attr="logs-table"]',
            },
            {
                id: SetupTaskId.SetUpLogAlerts,
                title: 'Set up log alerts',
                description: 'Get notified when specific log patterns occur.',
                buttonText: 'Create alert',
                taskType: 'explore',
                dependsOn: [SetupTaskId.ViewFirstLogs],
                getUrl: () => urls.alerts(),
                targetSelector: '[data-attr="manage-alerts-button"]',
            },
        ],
    },

    [ProductKey.WORKFLOWS]: {
        productKey: ProductKey.WORKFLOWS,
        title: 'Get started with Workflows',
        tasks: [
            {
                id: SetupTaskId.CreateFirstWorkflow,
                title: 'Create your first workflow',
                description: 'Build an automated workflow to engage users.',
                buttonText: 'Create workflow',
                taskType: 'onboarding',
                getUrl: () => urls.workflowNew(),
                targetSelector: '[data-attr="new-workflow"]',
            },
            {
                id: SetupTaskId.ConfigureWorkflowTrigger,
                title: 'Configure a trigger',
                description: 'Define when your workflow should start.',
                buttonText: 'Configure trigger',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.CreateFirstWorkflow],
                getUrl: () => urls.workflows(),
                targetSelector: '[data-attr="workflow-trigger"]',
            },
            {
                id: SetupTaskId.AddWorkflowAction,
                title: 'Add an action',
                description: 'Add actions like emails, Slack messages, or webhooks.',
                buttonText: 'Add action',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.ConfigureWorkflowTrigger],
                getUrl: () => urls.workflows(),
                targetSelector: '[data-attr="workflow-add-action"]',
            },
            {
                id: SetupTaskId.LaunchWorkflow,
                title: 'Launch your workflow',
                description: 'Activate your workflow to start engaging users.',
                buttonText: 'Launch',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.AddWorkflowAction],
                getUrl: () => urls.workflows(),
                targetSelector: '[data-attr="workflow-launch"]',
            },
        ],
    },

    [ProductKey.ENDPOINTS]: {
        productKey: ProductKey.ENDPOINTS,
        title: 'Get started with Endpoints',
        tasks: [
            {
                id: SetupTaskId.CreateFirstEndpoint,
                title: 'Create your first endpoint',
                description: 'Build an API endpoint to expose PostHog data.',
                buttonText: 'Create endpoint',
                taskType: 'onboarding',
                getUrl: () => urls.sqlEditor({ outputTab: OutputTab.Endpoint }),
                targetSelector: '[data-attr="new-endpoint-button"]',
            },
            {
                id: SetupTaskId.TestEndpoint,
                title: 'Test your endpoint',
                description: 'Use the playground to test with different parameters.',
                buttonText: 'Test endpoint',
                taskType: 'explore',
                dependsOn: [SetupTaskId.CreateFirstEndpoint],
                getUrl: () => urls.endpoints(),
                targetSelector: '[data-attr="endpoint-playground"]',
            },
            {
                id: SetupTaskId.ActivateEndpoint,
                title: 'Activate your endpoint',
                description: 'Make your endpoint accessible via the API.',
                buttonText: 'Activate',
                taskType: 'explore',
                dependsOn: [SetupTaskId.CreateFirstEndpoint],
                getUrl: () => urls.endpoints(),
                targetSelector: '[data-attr="endpoint-activate"]',
            },
        ],
    },

    [ProductKey.EARLY_ACCESS_FEATURES]: {
        productKey: ProductKey.EARLY_ACCESS_FEATURES,
        title: 'Get started with Early access features',
        tasks: [
            INGEST_FIRST_EVENT(ProductKey.EARLY_ACCESS_FEATURES),
            SET_UP_REVERSE_PROXY,
            {
                id: SetupTaskId.CreateEarlyAccessFeature,
                title: 'Create an early access feature',
                description: 'Set up a feature users can opt into before release.',
                buttonText: 'Create feature',
                taskType: 'onboarding',
                getUrl: () => urls.earlyAccessFeature('new'),
                targetSelector: '[data-attr="create-feature"]',
            },
            {
                id: SetupTaskId.UpdateFeatureStage,
                title: 'Update feature stage',
                description: 'Progress through: draft → concept → alpha → beta → GA.',
                buttonText: 'Update stage',
                taskType: 'explore',
                dependsOn: [SetupTaskId.CreateEarlyAccessFeature],
                getUrl: () => urls.earlyAccessFeatures(),
                targetSelector: '[data-attr="feature-stage"]',
            },
        ],
    },
}

// ============================================================================
// Helper Functions
// ============================================================================

/** Get the setup config for a product, or null if not configured */
export function getProductSetupConfig(productKey: ProductKey): ProductSetupConfig | null {
    return PRODUCT_SETUP_REGISTRY[productKey] ?? null
}

/** Get all tasks for a product, optionally filtered by type */
export function getTasksForProduct(
    productKey: ProductKey,
    taskType?: 'setup' | 'onboarding' | 'explore' | 'all'
): SetupTask[] {
    const config = getProductSetupConfig(productKey)
    if (!config) {
        return []
    }
    if (!taskType || taskType === 'all') {
        return config.tasks
    }
    return config.tasks.filter((t) => t.taskType === taskType)
}

/** List of products that have setup flows configured */
export const PRODUCTS_WITH_SETUP: ProductKey[] = Object.keys(PRODUCT_SETUP_REGISTRY) as ProductKey[]
