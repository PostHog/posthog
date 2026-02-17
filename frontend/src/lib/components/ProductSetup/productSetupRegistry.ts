import { urls } from 'scenes/urls'

import { AvailableSetupTaskIdsEnumApi as SetupTaskId } from '~/generated/core/api.schemas'
import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey, ReplayTabs } from '~/types'

import type { ProductSetupConfig, SetupTask } from './types'

// ============================================================================
// Shared Tasks - reusable across products
// ============================================================================

/** Ingest first event task - include in products that need event data */
export const INGEST_FIRST_EVENT = (productKey: ProductKey): SetupTask => ({
    id: SetupTaskId.ingest_first_event,
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
    id: SetupTaskId.set_up_reverse_proxy,
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
                id: SetupTaskId.create_first_insight,
                title: 'Create your first insight',
                description: 'Choose from various insight types to analyze user behavior.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.ingest_first_event],
                getUrl: () => urls.insights(),
                targetSelector: '[data-attr="saved-insights-new-insight-button"]',
            },
            {
                id: SetupTaskId.explore_trends_insight,
                title: 'Create a trends insight',
                description: 'Visualize how events or actions vary over time.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.create_first_insight],
                getUrl: () => urls.insightOptions(),
                targetSelector: '[data-attr="insight-option-trends"]',
            },
            {
                id: SetupTaskId.create_funnel,
                title: 'Create a funnel insight',
                description: 'Track how users move through steps like signup → activation → purchase.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.create_first_insight],
                getUrl: () => urls.insightOptions(),
                targetSelector: '[data-attr="insight-option-funnels"]',
            },
            {
                id: SetupTaskId.explore_retention_insight,
                title: 'Explore retention analysis',
                description: 'See how many users return on subsequent days after an initial action.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.create_first_insight],
                getUrl: () => urls.insightOptions(),
                targetSelector: '[data-attr="insight-option-retention"]',
            },
            {
                id: SetupTaskId.explore_paths_insight,
                title: 'Explore user paths',
                description: 'Trace the journeys users take within your product.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.create_first_insight],
                getUrl: () => urls.insightOptions(),
                targetSelector: '[data-attr="insight-option-paths"]',
            },
            {
                id: SetupTaskId.explore_stickiness_insight,
                title: 'Explore stickiness',
                description: 'See what keeps users coming back by viewing repeated actions.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.create_first_insight],
                getUrl: () => urls.insightOptions(),
                targetSelector: '[data-attr="insight-option-stickiness"]',
            },
            {
                id: SetupTaskId.explore_lifecycle_insight,
                title: 'Explore lifecycle analysis',
                description: 'Break down users into new, returning, resurrected, and dormant.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.create_first_insight],
                getUrl: () => urls.insightOptions(),
                targetSelector: '[data-attr="insight-option-lifecycle"]',
            },
            {
                id: SetupTaskId.create_first_dashboard,
                title: 'Create your first dashboard',
                description: 'Combine multiple insights into a dashboard to monitor key metrics.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.create_first_insight],
                getUrl: () => urls.dashboards(),
                targetSelector: '[data-attr="new-dashboard"]',
            },
            {
                id: SetupTaskId.track_custom_events,
                title: 'Track custom events',
                description: 'Go beyond autocapture by tracking specific actions that matter.',
                taskType: 'explore',
                requiresManualCompletion: true,
                docsUrl: 'https://posthog.com/tutorials/event-tracking-guide#setting-up-custom-events',
                targetSelector: '[data-attr="help-button"]',
            },
            {
                id: SetupTaskId.define_actions,
                title: 'Define actions',
                description: 'Group related events into actions for easier analysis.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.ingest_first_event],
                getUrl: () => urls.actions(),
                targetSelector: '[data-attr="create-action"]',
            },
            {
                id: SetupTaskId.set_up_cohorts,
                title: 'Create a user cohort',
                description: 'Group users based on behavior or properties for targeted analysis.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.ingest_first_event],
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
                id: SetupTaskId.add_authorized_domain,
                title: 'Add your domain',
                description: 'Authorize your website domain to enable accurate traffic tracking.',
                skipWarning: "Without a domain, you can't use the toolbar or categorize traffic properly.",
                taskType: 'setup',
                getUrl: () => urls.settings('environment-web-analytics'),
                targetSelector: '[data-attr="toolbar-add-url"]',
            },
            {
                id: SetupTaskId.set_up_web_vitals,
                title: 'Enable web vitals',
                description: 'Track Core Web Vitals (LCP, FID, CLS) to monitor site performance.',
                taskType: 'setup',
                getUrl: () => urls.settings('environment-autocapture'),
                targetSelector: '#posthog-autocapture-web-vitals-switch',
            },
            {
                id: SetupTaskId.review_web_analytics_dashboard,
                title: 'Review your dashboard',
                description: 'Explore pageviews, sessions, and user sources.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.ingest_first_event],
                getUrl: () => urls.webAnalytics(),
                targetSelector: '[data-attr="web-analytics-dashboard"]',
            },
            {
                id: SetupTaskId.filter_web_analytics,
                title: 'Filter your analytics',
                description: 'Filter data to focus on what matters to you.',
                taskType: 'explore',
                getUrl: () => urls.webAnalytics(),
                targetSelector: '[data-attr="web-analytics-unified-filters"]',
            },
            {
                id: SetupTaskId.set_up_web_analytics_conversion_goals,
                title: 'Set up conversion goals',
                description: 'Track important conversions like signups or purchases.',
                taskType: 'explore',
                getUrl: () => urls.webAnalytics(),
                targetSelector: '[data-attr="web-analytics-conversion-filter"]',
            },

            {
                id: SetupTaskId.visit_web_vitals_dashboard,
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
                id: SetupTaskId.setup_session_recordings,
                title: 'Enable session recordings',
                description: 'Turn on recording to capture user interactions.',
                skipWarning: 'Without recordings enabled, you cannot use session replay.',
                taskType: 'setup',
                getUrl: () => urls.replaySettings('replay'),
                targetSelector: '[data-attr="settings-menu-item-replay"]',
            },
            {
                id: SetupTaskId.configure_recording_settings,
                title: 'Configure recording settings',
                description: 'Customize sampling rate, privacy masking, and network capture.',
                taskType: 'setup',
                dependsOn: [SetupTaskId.setup_session_recordings],
                getUrl: () => urls.replaySettings('replay-triggers'),
                targetSelector: '[data-attr="settings-menu-item-replay-triggers"]',
            },
            {
                id: SetupTaskId.enable_console_logs,
                title: 'Enable console log capture',
                description: 'See JavaScript console logs alongside recordings for debugging.',
                taskType: 'setup',
                dependsOn: [SetupTaskId.setup_session_recordings],
                getUrl: () => urls.replaySettings('replay'),
                targetSelector: '[data-attr="opt-in-capture-console-log-switch"]',
            },
            {
                id: SetupTaskId.watch_session_recording,
                title: 'Watch your first recording',
                description: 'See exactly how a real user interacted with your product.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.setup_session_recordings],
                getUrl: () => urls.replay(ReplayTabs.Home),
                targetSelector: '[data-attr="session-recordings-playlist"]',
            },
            {
                id: SetupTaskId.create_recording_playlist,
                title: 'Create a recording playlist',
                description: 'Save filtered recordings for specific user journeys or issues.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.setup_session_recordings],
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
                id: SetupTaskId.create_feature_flag,
                title: 'Create your first feature flag',
                description: 'Create a flag to control feature rollouts without deploying.',
                taskType: 'onboarding',
                getUrl: () => urls.featureFlag('new'),
                targetSelector: '[data-attr="new-feature-flag"]',
            },
            {
                id: SetupTaskId.implement_flag_in_code,
                title: 'Implement flag in your code',
                description: 'Add the feature flag check to your application.',
                taskType: 'onboarding',
                requiresManualCompletion: true,
                dependsOn: [SetupTaskId.create_feature_flag],
                docsUrl: 'https://posthog.com/docs/feature-flags/installation',
                targetSelector: '[data-attr="help-button"]',
            },
            {
                id: SetupTaskId.update_feature_flag_release_conditions,
                title: 'Configure release conditions',
                description: 'Target specific users or percentages with your flag.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.create_feature_flag],
                docsUrl: 'https://posthog.com/docs/feature-flags/creating-feature-flags#release-conditions',
            },
            {
                id: SetupTaskId.create_multivariate_flag,
                title: 'Create a multivariate flag',
                description: 'Test multiple variants with different user groups.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.create_feature_flag],
                getUrl: () => urls.featureFlags(),
                targetSelector: '[data-attr="new-feature-flag"]',
            },
            {
                id: SetupTaskId.set_up_flag_payloads,
                title: 'Use flag payloads',
                description: 'Pass dynamic configuration to your feature flags.',
                taskType: 'explore',
                docsUrl: 'https://posthog.com/docs/feature-flags/creating-feature-flags#payloads',
            },
            {
                id: SetupTaskId.set_up_flag_evaluation_runtimes,
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
                id: SetupTaskId.create_experiment,
                title: 'Create your first experiment',
                description: 'Set up an A/B test to measure the impact of a change.',
                taskType: 'onboarding',
                getUrl: () => urls.experiments(),
                targetSelector: '[data-attr="create-experiment"]',
            },
            {
                id: SetupTaskId.implement_experiment_variants,
                title: 'Implement experiment variants in your code',
                description: 'Add code to show different variants to users.',
                taskType: 'onboarding',
                requiresManualCompletion: true,
                dependsOn: [SetupTaskId.create_experiment],
                docsUrl: 'https://posthog.com/docs/experiments/installation',
            },
            {
                id: SetupTaskId.launch_experiment,
                title: 'Launch your experiment',
                description: 'Start collecting data by launching your experiment.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.implement_experiment_variants],
                getUrl: () => urls.experiments(),
                targetSelector: '[data-attr="launch-experiment"]', // Will be highlighted once they click on an experiment
            },
            {
                id: SetupTaskId.review_experiment_results,
                title: 'Review experiment results',
                description: 'Analyze the statistical significance and impact.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.launch_experiment],
            },
        ],
    },

    [ProductKey.SURVEYS]: {
        productKey: ProductKey.SURVEYS,
        title: 'Get started with Surveys',
        tasks: [
            INGEST_FIRST_EVENT(ProductKey.SURVEYS),
            {
                id: SetupTaskId.create_survey,
                title: 'Create your first survey',
                description: 'Choose from templates or build a custom survey.',
                taskType: 'onboarding',
                getUrl: () => urls.surveys(),
                targetSelector: '[data-attr="new-survey"]',
            },
            {
                id: SetupTaskId.launch_survey,
                title: 'Launch your survey',
                description: 'Make your survey live and start collecting responses.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.create_survey],
                getUrl: () => urls.surveys(),
                targetSelector: '[data-attr="launch-survey"]', // Will be highlighted once they click on a survey
            },
        ],
    },

    [ProductKey.DATA_WAREHOUSE]: {
        productKey: ProductKey.DATA_WAREHOUSE,
        title: 'Get started with Data warehouse',
        tasks: [
            {
                id: SetupTaskId.connect_source,
                title: 'Connect your first data source',
                description: 'Import data from Stripe, Hubspot, Postgres, or other sources.',
                skipWarning: "Without a data source, you can't query data in the warehouse.",
                taskType: 'setup',
                getUrl: () => urls.dataWarehouseSourceNew(),
                targetSelector: '[data-attr="new-source-button"]',
            },
            {
                id: SetupTaskId.run_first_query,
                title: 'Run your first SQL query',
                description: 'Query your data using SQL in the data warehouse.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.connect_source],
                getUrl: () => urls.sqlEditor(),
                targetSelector: '[data-attr="sql-editor-button"]',
            },
            {
                id: SetupTaskId.join_external_data,
                title: 'Join external data with events',
                description: 'Combine PostHog events with external data.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.run_first_query],
                getUrl: () => urls.sqlEditor(),
                targetSelector: '[data-attr="sql-editor-button"]',
            },
            {
                id: SetupTaskId.create_saved_view,
                title: 'Save a view for reuse',
                description: 'Create a saved view from a query to use in insights.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.run_first_query],
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
                id: SetupTaskId.enable_error_tracking,
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
                id: SetupTaskId.upload_source_maps,
                title: 'Upload source maps',
                description: 'See readable stack traces instead of minified code.',
                skipWarning: "Without source maps, stack traces won't be readable.",
                taskType: 'setup',
                requiresManualCompletion: true,
                docsUrl: 'https://posthog.com/docs/error-tracking/upload-source-maps',
                targetSelector: '[data-attr="help-button"]',
            },
            {
                id: SetupTaskId.view_first_error,
                title: 'View your first error',
                description: 'Explore error details including stack trace and user context.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.enable_error_tracking],
                getUrl: () => urls.errorTracking(),
                targetSelector: '[data-attr="error-tracking-issue-row"]',
            },
            {
                id: SetupTaskId.resolve_first_error,
                title: 'Resolve an error',
                description: 'Mark an error as resolved to track your fix rate.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.view_first_error],
                getUrl: () => urls.errorTracking(),
                targetSelector: '[data-attr="error-tracking-resolve"]', // Will be highlighted once they click on an error
            },
        ],
    },

    [ProductKey.LLM_ANALYTICS]: {
        productKey: ProductKey.LLM_ANALYTICS,
        title: 'Get started with LLM analytics',
        tasks: [
            {
                id: SetupTaskId.ingest_first_llm_event,
                title: 'Send your first LLM event',
                description: 'Install the PostHog LLM SDK to start tracking AI usage.',
                skipWarning: "Without LLM events, you can't track AI model usage.",
                taskType: 'setup',
                getUrl: () =>
                    urls.onboarding({ productKey: ProductKey.LLM_ANALYTICS, stepKey: OnboardingStepKey.INSTALL }),
                targetSelector: '[data-attr="menu-item-llm_analytics"]',
            },
            {
                id: SetupTaskId.view_first_trace,
                title: 'View your first trace',
                description: 'See a complete LLM request trace with prompts and latency.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.ingest_first_event],
                getUrl: () => urls.llmAnalyticsTraces(),
                targetSelector: '[data-attr="llm-trace-table"]',
            },
            {
                id: SetupTaskId.track_costs,
                title: 'Track LLM costs and usage',
                description: 'Monitor AI spending and usage by model and use case.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.ingest_first_event],
                getUrl: () => urls.llmAnalyticsDashboard(),
            },
            {
                id: SetupTaskId.set_up_llm_evaluation,
                title: 'Set up LLM evaluation',
                description: 'Score and evaluate LLM outputs for quality.',
                taskType: 'explore',
                getUrl: () => urls.llmAnalyticsEvaluations(),
            },
            {
                id: SetupTaskId.run_ai_playground,
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
                id: SetupTaskId.enable_revenue_analytics_viewset,
                title: 'Enable Revenue Analytics viewset',
                description: 'Enable the Revenue Analytics viewset to start tracking revenue data.',
                skipWarning: 'You need a revenue source to view revenue analytics.',
                taskType: 'setup',
                getUrl: () => urls.revenueAnalytics(),
                targetSelector: '[data-attr="managed-viewset-toggle"]',
            },
            {
                id: SetupTaskId.connect_revenue_source,
                title: 'Connect a revenue source',
                description: 'Import revenue data from Stripe or another provider.',
                skipWarning: 'You need a revenue source to view revenue analytics.',
                taskType: 'setup',
                getUrl: () => urls.revenueAnalytics(),
                targetSelector: '[data-attr="new-source-button"]',
            },
            {
                id: SetupTaskId.set_up_revenue_goal,
                title: 'Set up a revenue goal',
                description: 'Track progress towards your MRR or revenue targets.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.connect_revenue_source],
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
                id: SetupTaskId.enable_log_capture,
                title: 'Enable log capture',
                description: 'Start sending logs from your application to PostHog.',
                taskType: 'setup',
                requiresManualCompletion: true,
                docsUrl: 'https://posthog.com/docs/logs',
            },
            {
                id: SetupTaskId.view_first_logs,
                title: 'View your logs',
                description: 'Explore application logs with filtering and search.',
                taskType: 'onboarding',
                dependsOn: [SetupTaskId.enable_log_capture],
                getUrl: () => urls.logs(),
            },
        ],
    },

    [ProductKey.WORKFLOWS]: {
        productKey: ProductKey.WORKFLOWS,
        title: 'Get started with Workflows',
        tasks: [
            {
                id: SetupTaskId.set_up_first_workflow_channel,
                title: 'Set up your first workflows channel',
                description: 'Connect a channel like email, Slack, or Twilio for sending messages.',
                taskType: 'onboarding',
                getUrl: () => urls.workflows('channels'),
                targetSelector: '[data-attr="new-channel-button"]',
            },
            {
                id: SetupTaskId.create_first_workflow,
                title: 'Create your first workflow',
                description: 'Build an automated workflow to engage users.',
                taskType: 'onboarding',
                getUrl: () => urls.workflows(),
                targetSelector: '[data-attr="new-workflow"]',
            },
            {
                id: SetupTaskId.configure_workflow_trigger,
                title: 'Configure a trigger',
                description: 'Define when your workflow should start.',
                taskType: 'onboarding',
                targetSelector: '[data-attr="workflow-trigger"]', // Will be highlighted once they are inside a workflow
            },
            {
                id: SetupTaskId.add_workflow_action,
                title: 'Add an action',
                description: 'Add actions like emails, Slack messages, or webhooks.',
                taskType: 'onboarding',
                targetSelector: '[data-attr="workflow-add-action"]', // Will be highlighted once they are inside a workflow
            },
            {
                id: SetupTaskId.launch_workflow,
                title: 'Launch your workflow',
                description: 'Activate your workflow to start engaging users.',
                taskType: 'onboarding',
                dependsOn: [
                    SetupTaskId.create_first_workflow,
                    SetupTaskId.configure_workflow_trigger,
                    SetupTaskId.add_workflow_action,
                ],
                targetSelector: '[data-attr="workflow-launch"]', // Will be highlighted once they click on a workflow
            },
        ],
    },

    [ProductKey.ENDPOINTS]: {
        productKey: ProductKey.ENDPOINTS,
        title: 'Get started with Endpoints',
        tasks: [
            {
                id: SetupTaskId.create_first_endpoint,
                title: 'Create your first endpoint',
                description: 'Build an API endpoint to expose PostHog data.',
                taskType: 'onboarding',
                getUrl: () => urls.endpoints(),
                targetSelector: '[data-attr="new-endpoint-button"]',
            },
            {
                id: SetupTaskId.configure_endpoint,
                title: 'Configure your endpoint',
                description: 'Configure your endpoint caching and materialization mechanisms.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.create_first_endpoint],
                targetSelector: '[data-attr="endpoint-configuration-tab"]', // Will be highlighted once they are inside an endpoint
            },
            {
                id: SetupTaskId.test_endpoint,
                title: 'Test your endpoint',
                description: 'Use the playground to test with different parameters.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.create_first_endpoint],
                targetSelector: '[data-attr="endpoint-playground-tab"]', // Will be highlighted once they are inside an endpoint
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
                id: SetupTaskId.create_early_access_feature,
                title: 'Create an early access feature',
                description: 'Set up a feature users can opt into before release.',
                taskType: 'onboarding',
                getUrl: () => urls.earlyAccessFeatures(),
                targetSelector: '[data-attr="create-feature"]',
            },
            {
                id: SetupTaskId.update_feature_stage,
                title: 'Update feature stage',
                description: 'Progress through: draft → concept → alpha → beta → GA.',
                taskType: 'explore',
                dependsOn: [SetupTaskId.create_early_access_feature],
                targetSelector: '[data-attr="feature-stage"]', // Will be highlighted once they are inside a feature
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
