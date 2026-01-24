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
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.IngestFirstEvent],
                getUrl: () => urls.insightNew({ type: InsightType.TRENDS }),
            },
            {
                id: SetupTaskId.CreateFunnel,
                title: 'Create a funnel insight',
                description: 'Track how users move through steps like signup → activation → purchase.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.IngestFirstEvent],
                getUrl: () => urls.insightNew({ type: InsightType.FUNNELS }),
            },
            {
                id: SetupTaskId.CreateFirstDashboard,
                title: 'Create your first dashboard',
                description: 'Combine multiple insights into a dashboard to monitor key metrics.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.CreateFirstInsight],
                getUrl: () => urls.dashboards(),
                targetSelector: '[data-attr="new-dashboard"]',
            },
            {
                id: SetupTaskId.TrackCustomEvents,
                title: 'Track custom events',
                description: 'Go beyond autocapture by tracking specific actions that matter.',
                taskType: 'explore',
                requiresManualCompletion: true,
                docsUrl: 'https://posthog.com/tutorials/event-tracking-guide#setting-up-custom-events',
                targetSelector: '[data-attr="help-button"]',
            },
            {
                id: SetupTaskId.DefineActions,
                title: 'Define actions',
                description: 'Group related events into actions for easier analysis.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.IngestFirstEvent],
                getUrl: () => urls.actions(),
                targetSelector: '[data-attr="create-action"]',
            },
            {
                id: SetupTaskId.SetUpCohorts,
                title: 'Create a user cohort',
                description: 'Group users based on behavior or properties for targeted analysis.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.IngestFirstEvent],
                getUrl: () => urls.cohorts(),
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
                skipWarning: "Without a domain, you can't use the toolbar or categorize traffic properly.",
                taskType: 'setup',
                getUrl: () => urls.settings('environment-web-analytics'),
                targetSelector: '[data-attr="toolbar-add-url"]',
            },
            {
                id: SetupTaskId.SetUpWebVitals,
                title: 'Enable web vitals',
                description: 'Track Core Web Vitals (LCP, FID, CLS) to monitor site performance.',
                taskType: 'setup',
                getUrl: () => urls.settings('environment-autocapture'),
                targetSelector: '#posthog-autocapture-web-vitals-switch',
            },
            {
                id: SetupTaskId.ReviewWebAnalyticsDashboard,
                title: 'Review your dashboard',
                description: 'Explore pageviews, sessions, and user sources.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.IngestFirstEvent],
                getUrl: () => urls.webAnalytics(),
                targetSelector: '[data-attr="web-analytics-dashboard"]',
            },
            {
                id: SetupTaskId.FilterWebAnalytics,
                title: 'Filter your analytics',
                description: 'Filter data to focus on what matters to you.',
                taskType: 'explore',
                getUrl: () => urls.webAnalytics(),
                targetSelector: '[data-attr="web-analytics-unified-filters"]',
            },
            {
                id: SetupTaskId.SetUpWebAnalyticsConversionGoals,
                title: 'Set up conversion goals',
                description: 'Track important conversions like signups or purchases.',
                taskType: 'explore',
                getUrl: () => urls.webAnalytics(),
                targetSelector: '[data-attr="web-analytics-conversion-filter"]',
            },

            {
                id: SetupTaskId.VisitWebVitalsDashboard,
                title: 'Visit your web vitals dashboard',
                description: 'Monitor your site performance over time.',
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
                skipWarning: 'Without recordings enabled, you cannot use session replay.',
                taskType: 'setup',
                getUrl: () => urls.replaySettings('replay'),
                targetSelector: '[data-attr="settings-menu-item-replay"]',
            },
            {
                id: SetupTaskId.ConfigureRecordingSettings,
                title: 'Configure recording settings',
                description: 'Customize sampling rate, privacy masking, and network capture.',
                taskType: 'setup',
                dependsOn: [SetupTaskId.SetupSessionRecordings],
                getUrl: () => urls.replaySettings('replay-triggers'),
                targetSelector: '[data-attr="settings-menu-item-replay-triggers"]',
            },
            {
                id: SetupTaskId.EnableConsoleLogs,
                title: 'Enable console log capture',
                description: 'See JavaScript console logs alongside recordings for debugging.',
                taskType: 'setup',
                dependsOn: [SetupTaskId.SetupSessionRecordings],
                getUrl: () => urls.replaySettings('replay'),
                targetSelector: '[data-attr="opt-in-capture-console-log-switch"]',
            },
            {
                id: SetupTaskId.WatchSessionRecording,
                title: 'Watch your first recording',
                description: 'See exactly how a real user interacted with your product.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.SetupSessionRecordings],
                getUrl: () => urls.replay(ReplayTabs.Home),
                targetSelector: '[data-attr="session-recordings-playlist"]',
            },
            {
                id: SetupTaskId.CreateRecordingPlaylist,
                title: 'Create a recording playlist',
                description: 'Save filtered recordings for specific user journeys or issues.',
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
                taskType: 'onboarding',
                getUrl: () => urls.featureFlag('new'),
                targetSelector: '[data-attr="new-feature-flag"]',
            },
            {
                id: SetupTaskId.ImplementFlagInCode,
                title: 'Implement flag in your code',
                description: 'Add the feature flag check to your application.',
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
                taskType: 'explore',
                dependsOn: [SetupTaskId.CreateFeatureFlag],
                docsUrl: 'https://posthog.com/docs/feature-flags/creating-feature-flags#release-conditions',
            },
            {
                id: SetupTaskId.CreateMultivariateFlag,
                title: 'Create a multivariate flag',
                description: 'Test multiple variants with different user groups.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.CreateFeatureFlag],
                getUrl: () => urls.featureFlags(),
                targetSelector: '[data-attr="new-feature-flag"]',
            },
            {
                id: SetupTaskId.SetUpFlagPayloads,
                title: 'Use flag payloads',
                description: 'Pass dynamic configuration to your feature flags.',
                taskType: 'explore',
                docsUrl: 'https://posthog.com/docs/feature-flags/creating-feature-flags#payloads',
            },
            {
                id: SetupTaskId.SetUpFlagEvaluationRuntimes,
                title: 'Set up flag evaluation runtimes',
                description: 'Control where your feature flags can be evaluated.',
                taskType: 'explore',
                docsUrl:
                    'https://posthog.com/docs/feature-flags/creating-feature-flags#step-5-configure-evaluation-runtime-and-contexts-optional',
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
                taskType: 'onboarding',
                getUrl: () => urls.experiments(),
                targetSelector: '[data-attr="create-experiment"]',
            },
            {
                id: SetupTaskId.ImplementExperimentVariants,
                title: 'Implement experiment variants in your code',
                description: 'Add code to show different variants to users.',
                taskType: 'onboarding',
                requiresManualCompletion: true,
                dependsOn: [SetupTaskId.CreateExperiment],
                docsUrl: 'https://posthog.com/docs/experiments/installation',
            },
            {
                id: SetupTaskId.LaunchExperiment,
                title: 'Launch your experiment',
                description: 'Start collecting data by launching your experiment.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.ImplementExperimentVariants],
                getUrl: () => urls.experiments(),
                targetSelector: '[data-attr="launch-experiment"]',
            },
            {
                id: SetupTaskId.ReviewExperimentResults,
                title: 'Review experiment results',
                description: 'Analyze the statistical significance and impact.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.LaunchExperiment],
                getUrl: () => urls.experiments(),
                targetSelector: '[data-attr="experiments-table-container"]',
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
                taskType: 'onboarding',
                getUrl: () => urls.surveyTemplates(),
                targetSelector: '[data-attr="new-survey"]',
            },
            {
                id: SetupTaskId.LaunchSurvey,
                title: 'Launch your survey',
                description: 'Make your survey live and start collecting responses.',
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
                skipWarning: "Without a data source, you can't query data in the warehouse.",
                taskType: 'setup',
                getUrl: () => urls.dataWarehouseSourceNew(),
                targetSelector: '[data-attr="new-source-button"]',
            },
            {
                id: SetupTaskId.RunFirstQuery,
                title: 'Run your first SQL query',
                description: 'Query your data using SQL in the data warehouse.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.ConnectFirstSource],
                getUrl: () => urls.sqlEditor(),
                targetSelector: '[data-attr="sql-editor-button"]',
            },
            {
                id: SetupTaskId.JoinExternalData,
                title: 'Join external data with events',
                description: 'Combine PostHog events with external data.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.RunFirstQuery],
                getUrl: () => urls.sqlEditor(),
                targetSelector: '[data-attr="sql-editor-button"]',
            },
            {
                id: SetupTaskId.CreateSavedView,
                title: 'Save a view for reuse',
                description: 'Create a saved view from a query to use in insights.',
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
                skipWarning: "Without source maps, stack traces won't be readable.",
                taskType: 'setup',
                requiresManualCompletion: true,
                docsUrl: 'https://posthog.com/docs/error-tracking/upload-source-maps',
                targetSelector: '[data-attr="help-button"]',
            },
            {
                id: SetupTaskId.ViewFirstError,
                title: 'View your first error',
                description: 'Explore error details including stack trace and user context.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.EnableErrorTracking],
                getUrl: () => urls.errorTracking(),
                targetSelector: '[data-attr="error-tracking-issue-row"]',
            },
            {
                id: SetupTaskId.ResolveFirstError,
                title: 'Resolve an error',
                description: 'Mark an error as resolved to track your fix rate.',
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
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.IngestFirstEvent],
                getUrl: () => urls.llmAnalyticsTraces(),
                targetSelector: '[data-attr="llm-trace-table"]',
            },
            {
                id: SetupTaskId.TrackCosts,
                title: 'Track LLM costs and usage',
                description: 'Monitor AI spending and usage by model and use case.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.IngestFirstEvent],
                getUrl: () => urls.llmAnalyticsDashboard(),
            },
            {
                id: SetupTaskId.SetUpLlmEvaluation,
                title: 'Set up LLM evaluation',
                description: 'Score and evaluate LLM outputs for quality.',
                taskType: 'explore',
                getUrl: () => urls.llmAnalyticsEvaluations(),
            },
            {
                id: SetupTaskId.RunAIPlayground,
                title: 'Run your first AI playground',
                description: 'Test and refine your AI prompts with real-time feedback.',
                taskType: 'explore',
                getUrl: () => urls.llmAnalyticsPlayground(),
                targetSelector: '[data-attr="ai-playground-run-button"]',
            },
        ],
    },

    [ProductKey.REVENUE_ANALYTICS]: {
        productKey: ProductKey.REVENUE_ANALYTICS,
        title: 'Get started with Revenue analytics',
        tasks: [
            {
                id: SetupTaskId.EnableRevenueAnalyticsViewset,
                title: 'Enable Revenue Analytics viewset',
                description: 'Enable the Revenue Analytics viewset to start tracking revenue data.',
                skipWarning: 'You need a revenue source to view revenue analytics.',
                taskType: 'setup',
                getUrl: () => urls.revenueAnalytics(),
                targetSelector: '[data-attr="managed-viewset-toggle"]',
            },
            {
                id: SetupTaskId.ConnectRevenueSource,
                title: 'Connect a revenue source',
                description: 'Import revenue data from Stripe or another provider.',
                skipWarning: 'You need a revenue source to view revenue analytics.',
                taskType: 'setup',
                getUrl: () => urls.revenueAnalytics(),
                targetSelector: '[data-attr="new-source-button"]',
            },
            {
                id: SetupTaskId.SetUpRevenueGoal,
                title: 'Set up a revenue goal',
                description: 'Track progress towards your MRR or revenue targets.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.ConnectRevenueSource],
                getUrl: () => urls.revenueSettings(),
                targetSelector: '[data-attr="revenue-analytics-add-goal-button"]',
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
                taskType: 'setup',
                requiresManualCompletion: true,
                docsUrl: 'https://posthog.com/docs/logs',
            },
            {
                id: SetupTaskId.ViewFirstLogs,
                title: 'View your logs',
                description: 'Explore application logs with filtering and search.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.EnableLogCapture],
                getUrl: () => urls.logs(),
                targetSelector: '[data-attr="logs-table"]',
            },
            {
                id: SetupTaskId.SetUpLogAlerts,
                title: 'Set up log alerts',
                description: 'Get notified when specific log patterns occur.',
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
                taskType: 'onboarding',
                getUrl: () => urls.workflows(),
                targetSelector: '[data-attr="new-workflow"]',
            },
            {
                id: SetupTaskId.ConfigureWorkflowTrigger,
                title: 'Configure a trigger',
                description: 'Define when your workflow should start.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.CreateFirstWorkflow],
                targetSelector: '[data-attr="workflow-trigger"]',
            },
            {
                id: SetupTaskId.AddWorkflowAction,
                title: 'Add an action',
                description: 'Add actions like emails, Slack messages, or webhooks.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.ConfigureWorkflowTrigger],
                targetSelector: '[data-attr="workflow-add-action"]',
            },
            {
                id: SetupTaskId.LaunchWorkflow,
                title: 'Launch your workflow',
                description: 'Activate your workflow to start engaging users.',
                taskType: 'onboarding',
                dependsOn: [
                    SetupTaskId.CreateFirstWorkflow,
                    SetupTaskId.ConfigureWorkflowTrigger,
                    SetupTaskId.AddWorkflowAction,
                ],
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
                taskType: 'onboarding',
                getUrl: () => urls.sqlEditor({ outputTab: OutputTab.Endpoint }),
                targetSelector: '[data-attr="new-endpoint-button"]',
            },
            {
                id: SetupTaskId.ConfigureEndpoint,
                title: 'Configure your endpoint',
                description: 'Configure your endpoint caching and materialization mechanisms.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.CreateFirstEndpoint],
                targetSelector: '[data-attr="endpoint-configuration-tab"]',
            },
            {
                id: SetupTaskId.TestEndpoint,
                title: 'Test your endpoint',
                description: 'Use the playground to test with different parameters.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.CreateFirstEndpoint],
                targetSelector: '[data-attr="endpoint-playground-tab"]',
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
                taskType: 'onboarding',
                getUrl: () => urls.earlyAccessFeatures(),
                targetSelector: '[data-attr="create-feature"]',
            },
            {
                id: SetupTaskId.UpdateFeatureStage,
                title: 'Update feature stage',
                description: 'Progress through: draft → concept → alpha → beta → GA.',
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
