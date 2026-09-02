import { Meta } from '@storybook/react'

import type { Mocks } from '~/mocks/utils'

import { actionsEmptyState } from 'products/actions/frontend/emptyState/actionsEmptyState'
import { aiObservabilityEmptyState } from 'products/ai_observability/frontend/emptyState/aiObservabilityEmptyState'
import { llmPromptsEmptyState } from 'products/ai_observability/frontend/emptyState/llmPromptsEmptyState'
import { annotationsEmptyState } from 'products/annotations/frontend/emptyState/annotationsEmptyState'
import { webScriptsEmptyState } from 'products/cdp/frontend/emptyState/webScriptsEmptyState'
import { cohortsEmptyState } from 'products/cohorts/frontend/emptyState/cohortsEmptyState'
import { supportEmptyState } from 'products/conversations/frontend/emptyState/supportEmptyState'
import { dashboardsEmptyState } from 'products/dashboards/frontend/emptyState/dashboardsEmptyState'
import { dataWarehouseEmptyState } from 'products/data_warehouse/frontend/emptyState/dataWarehouseEmptyState'
import { earlyAccessFeaturesEmptyState } from 'products/early_access_features/frontend/emptyState/earlyAccessFeaturesEmptyState'
import { endpointsEmptyState } from 'products/endpoints/frontend/emptyState/endpointsEmptyState'
import { errorTrackingEmptyState } from 'products/error_tracking/frontend/emptyState/errorTrackingEmptyState'
import { experimentsEmptyState } from 'products/experiments/frontend/emptyState/experimentsEmptyState'
import { featureFlagsEmptyState } from 'products/feature_flags/frontend/emptyState/featureFlagsEmptyState'
import { linksEmptyState } from 'products/links/frontend/emptyState/linksEmptyState'
import { logsEmptyState } from 'products/logs/frontend/emptyState/logsEmptyState'
import { marketingAnalyticsEmptyState } from 'products/marketing_analytics/frontend/emptyState/marketingAnalyticsEmptyState'
import { mcpAnalyticsEmptyState } from 'products/mcp_analytics/frontend/emptyState/mcpAnalyticsEmptyState'
import { metricsEmptyState } from 'products/metrics/frontend/emptyState/metricsEmptyState'
import { productAnalyticsEmptyState } from 'products/product_analytics/frontend/emptyState/productAnalyticsEmptyState'
import { productToursEmptyState } from 'products/product_tours/frontend/emptyState/productToursEmptyState'
import { sessionReplayEmptyState } from 'products/replay/frontend/emptyState/sessionReplayEmptyState'
import { replayVisionEmptyState } from 'products/replay_vision/frontend/emptyState/replayVisionEmptyState'
import { llmSkillsEmptyState } from 'products/skills/frontend/emptyState/llmSkillsEmptyState'
import { surveysEmptyState } from 'products/surveys/frontend/emptyState/surveysEmptyState'
import { tracingEmptyState } from 'products/tracing/frontend/emptyState/tracingEmptyState'
import { userInterviewsEmptyState } from 'products/user_interviews/frontend/emptyState/userInterviewsEmptyState'
import { webVitalsEmptyState } from 'products/web_analytics/frontend/emptyState/webVitalsEmptyState'
import { workflowsEmptyState } from 'products/workflows/frontend/emptyState/workflowsEmptyState'

import { ProductEmptyState } from './ProductEmptyState'
import { ProductEmptyStateStory, productEmptyStateStory } from './storybookHelpers'

// Every adopting product renders its real empty-state config here (the exact object
// its scene gate uses) via productEmptyStateStory, so storybook and visual regression
// cover the shipped surface rather than a demo.

/**
 * The MCP status indicator polls a signal query - answer it per story so the
 * indicator matches the story's mode. Signal row shape:
 * [has_initialize, tool_calls_total, tool_calls_7d, first_call_at]
 */
function mcpSignalMocks(hasInitialize: boolean): Mocks {
    return {
        post: {
            '/api/environments/:team_id/query/:kind': [
                200,
                { results: [[hasInitialize, 0, 0, '1970-01-01T00:00:00Z']] },
            ],
        },
    }
}

const meta: Meta<typeof ProductEmptyState> = {
    title: 'Components/Product Empty State',
    component: ProductEmptyState,
}
export default meta

export const MCPAnalyticsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(
    mcpAnalyticsEmptyState,
    'needs-setup',
    { mocks: mcpSignalMocks(false) }
)

export const MCPAnalyticsWaitingForData: ProductEmptyStateStory = productEmptyStateStory(
    mcpAnalyticsEmptyState,
    'waiting-for-data',
    { mocks: mcpSignalMocks(true) }
)

// No wizard configured (the self-hosted rendering, where the terminal hides and the
// manual setup path is promoted).
export const MCPAnalyticsWithoutWizard: ProductEmptyStateStory = productEmptyStateStory(
    mcpAnalyticsEmptyState,
    'needs-setup',
    { config: { wizard: undefined }, mocks: mcpSignalMocks(false) }
)

// The detection logics for flags and experiments count entities on mount - answer
// with an empty list so the story renders the shipped needs-setup surface.
const emptyEntityList = { count: 0, next: null, previous: null, results: [] }

export const FeatureFlagsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(
    featureFlagsEmptyState,
    'needs-setup',
    { mocks: { get: { '/api/projects/:team_id/feature_flags/': [200, emptyEntityList] } } }
)

export const ExperimentsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(
    experimentsEmptyState,
    'needs-setup',
    { mocks: { get: { '/api/projects/:team_id/experiments/': [200, emptyEntityList] } } }
)

export const EarlyAccessFeaturesNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(
    earlyAccessFeaturesEmptyState,
    'needs-setup',
    { mocks: { get: { '/api/projects/:team_id/early_access_feature/': [200, emptyEntityList] } } }
)

export const LLMPromptsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(
    llmPromptsEmptyState,
    'needs-setup',
    {
        mocks: { get: { '/api/projects/:team_id/llm_prompts/': [200, emptyEntityList] } },
    }
)

export const SkillsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(llmSkillsEmptyState, 'needs-setup', {
    mocks: { get: { '/api/projects/:team_id/llm_skills/': [200, emptyEntityList] } },
})

export const EndpointsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(endpointsEmptyState, 'needs-setup', {
    mocks: { get: { '/api/projects/:team_id/endpoints/': [200, emptyEntityList] } },
})

export const UserInterviewsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(
    userInterviewsEmptyState,
    'needs-setup',
    { mocks: { get: { '/api/projects/:team_id/user_interview_topics/': [200, emptyEntityList] } } }
)

export const LinksNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(linksEmptyState, 'needs-setup', {
    mocks: { get: { '/api/projects/:team_id/links/': [200, emptyEntityList] } },
})

export const ProductToursNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(
    productToursEmptyState,
    'needs-setup',
    { mocks: { get: { '/api/projects/:team_id/product_tours/': [200, emptyEntityList] } } }
)

export const SupportNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(supportEmptyState, 'needs-setup', {
    mocks: { get: { '/api/projects/:team_id/conversations/tickets/': [200, emptyEntityList] } },
})

export const SupportWaitingForData: ProductEmptyStateStory = productEmptyStateStory(
    supportEmptyState,
    'waiting-for-data',
    { mocks: { get: { '/api/projects/:team_id/conversations/tickets/': [200, emptyEntityList] } } }
)

export const WebScriptsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(
    webScriptsEmptyState,
    'needs-setup',
    {
        mocks: { get: { '/api/projects/:team_id/hog_functions/': [200, emptyEntityList] } },
    }
)

// AI observability detection is binary (no waiting-for-data middle state).
export const AIObservabilityNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(
    aiObservabilityEmptyState,
    'needs-setup'
)

// Replay vision detection is binary too (a scanner is the unit of setup); its
// detection logic polls the scanner stats endpoint, so answer it with zeros.
export const ReplayVisionNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(
    replayVisionEmptyState,
    'needs-setup',
    {
        mocks: {
            get: {
                '/api/projects/:team_id/vision/scanners/stats/': {
                    total: 0,
                    enabled: 0,
                    by_type: {
                        monitor: { enabled: 0, total: 0 },
                        classifier: { enabled: 0, total: 0 },
                        scorer: { enabled: 0, total: 0 },
                        summarizer: { enabled: 0, total: 0 },
                    },
                },
            },
        },
    }
)

// Actions detection lists actions on mount - answer "none yet".
const actionsMocks = {
    get: { '/api/projects/:team_id/actions/': [200, { count: 0, results: [] }] },
} as const

export const ActionsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(actionsEmptyState, 'needs-setup', {
    mocks: actionsMocks,
})

// Annotations detection lists annotations on mount - answer "none yet".
const annotationsMocks = {
    get: { '/api/projects/:team_id/annotations/': [200, { count: 0, results: [] }] },
} as const

export const AnnotationsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(
    annotationsEmptyState,
    'needs-setup',
    { mocks: annotationsMocks }
)

// Cohorts detection lists cohorts on mount - answer "none yet".
const cohortsMocks = {
    get: { '/api/projects/:team_id/cohorts/': [200, { count: 0, results: [] }] },
} as const

export const CohortsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(cohortsEmptyState, 'needs-setup', {
    mocks: cohortsMocks,
})

// Dashboards detection lists dashboards on mount - answer "none yet".
const dashboardsMocks = {
    get: { '/api/projects/:team_id/dashboards/': [200, { count: 0, results: [] }] },
} as const

export const DashboardsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(
    dashboardsEmptyState,
    'needs-setup',
    { mocks: dashboardsMocks }
)

// Product analytics detection lists insights on mount - answer "none yet".
const productAnalyticsMocks = {
    get: { '/api/projects/:team_id/insights/': [200, { count: 0, results: [] }] },
} as const

export const ProductAnalyticsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(
    productAnalyticsEmptyState,
    'needs-setup',
    { mocks: productAnalyticsMocks }
)

// Error tracking detection asks the issues-exists API on mount - answer "none yet".
const errorTrackingMocks = {
    get: { '/api/projects/:team_id/error_tracking/issues/exists/': [200, { exists: false }] },
} as const

export const ErrorTrackingNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(
    errorTrackingEmptyState,
    'needs-setup',
    { mocks: errorTrackingMocks }
)

export const ErrorTrackingWaitingForData: ProductEmptyStateStory = productEmptyStateStory(
    errorTrackingEmptyState,
    'waiting-for-data',
    { mocks: errorTrackingMocks }
)

// Logs detection asks the has-logs API on mount - answer "none yet".
export const LogsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(logsEmptyState, 'needs-setup', {
    // nosemgrep: no-environments-api-urls-frontend -- api.logs is env-scoped, so the msw mock must match /api/environments to intercept it
    mocks: { get: { '/api/environments/:team_id/logs/has_logs': [200, { hasLogs: false }] } },
})

// Tracing detection asks the has-spans API on mount - answer "none yet".
export const TracingNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(tracingEmptyState, 'needs-setup', {
    // nosemgrep: no-environments-api-urls-frontend -- api.tracing is env-scoped, so the msw mock must match /api/environments to intercept it
    mocks: { get: { '/api/environments/:team_id/tracing/spans/has_spans': [200, { hasSpans: false }] } },
})

// Metrics detection asks the has-metrics API on mount - answer "none yet".
export const MetricsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(metricsEmptyState, 'needs-setup', {
    mocks: { get: { '/api/projects/:team_id/metrics/has_metrics/': [200, { hasMetrics: false }] } },
})

// Surveys detection counts surveys (live + archived) on mount - answer "none yet".
export const SurveysNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(surveysEmptyState, 'needs-setup', {
    mocks: { get: { '/api/projects/:team_id/surveys/': [200, { count: 0, results: [] }] } },
})

// Session replay detection lists recordings on mount - answer "none yet".
const sessionReplayMocks = {
    // nosemgrep: no-environments-api-urls-frontend -- api.recordings is env-scoped, so the msw mock must match /api/environments to intercept it
    get: { '/api/environments/:team_id/session_recordings': [200, { results: [] }] },
} as const

export const SessionReplayNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(
    sessionReplayEmptyState,
    'needs-setup',
    { mocks: sessionReplayMocks }
)

export const SessionReplayWaitingForData: ProductEmptyStateStory = productEmptyStateStory(
    sessionReplayEmptyState,
    'waiting-for-data',
    { mocks: sessionReplayMocks }
)

// Web vitals detection asks event definitions on mount - answer "none yet".
const webVitalsMocks = {
    get: { '/api/projects/:team_id/event_definitions/': [200, { results: [] }] },
} as const

export const WebVitalsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(webVitalsEmptyState, 'needs-setup', {
    mocks: webVitalsMocks,
})

export const WebVitalsWaitingForData: ProductEmptyStateStory = productEmptyStateStory(
    webVitalsEmptyState,
    'waiting-for-data',
    { mocks: webVitalsMocks }
)

// Data warehouse detection lists sources and tables on mount - answer "none yet".
export const DataWarehouseNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(
    dataWarehouseEmptyState,
    'needs-setup',
    {
        mocks: {
            get: {
                // nosemgrep: no-environments-api-urls-frontend -- both APIs are env-scoped, so the msw mocks must match /api/environments to intercept them
                '/api/environments/:team_id/external_data_sources/': [200, { results: [] }],
                '/api/environments/:team_id/warehouse_tables/': [200, { results: [] }],
            },
        },
    }
)

// Workflows detection counts workflows on mount - answer "none yet".
export const WorkflowsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(workflowsEmptyState, 'needs-setup', {
    mocks: { get: { '/api/projects/:team_id/hog_flows/': [200, { count: 0, results: [] }] } },
})

// Marketing analytics detection mirrors the scene logic's sources check; the
// default query mocks answer its source queries with empty results.
export const MarketingAnalyticsNeedsSetup: ProductEmptyStateStory = productEmptyStateStory(
    marketingAnalyticsEmptyState,
    'needs-setup',
    {
        mocks: {
            get: {
                // nosemgrep: no-environments-api-urls-frontend -- the sources API is env-scoped, so the msw mock must match /api/environments to intercept it
                '/api/environments/:team_id/external_data_sources/': [200, { results: [] }],
            },
        },
    }
)
