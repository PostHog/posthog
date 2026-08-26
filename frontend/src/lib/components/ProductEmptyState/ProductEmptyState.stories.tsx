import { Meta } from '@storybook/react'

import type { Mocks } from '~/mocks/utils'

import { aiObservabilityEmptyState } from 'products/ai_observability/frontend/emptyState/aiObservabilityEmptyState'
import { llmPromptsEmptyState } from 'products/ai_observability/frontend/emptyState/llmPromptsEmptyState'
import { webScriptsEmptyState } from 'products/cdp/frontend/emptyState/webScriptsEmptyState'
import { supportEmptyState } from 'products/conversations/frontend/emptyState/supportEmptyState'
import { earlyAccessFeaturesEmptyState } from 'products/early_access_features/frontend/emptyState/earlyAccessFeaturesEmptyState'
import { endpointsEmptyState } from 'products/endpoints/frontend/emptyState/endpointsEmptyState'
import { experimentsEmptyState } from 'products/experiments/frontend/emptyState/experimentsEmptyState'
import { featureFlagsEmptyState } from 'products/feature_flags/frontend/emptyState/featureFlagsEmptyState'
import { linksEmptyState } from 'products/links/frontend/emptyState/linksEmptyState'
import { mcpAnalyticsEmptyState } from 'products/mcp_analytics/frontend/emptyState/mcpAnalyticsEmptyState'
import { productToursEmptyState } from 'products/product_tours/frontend/emptyState/productToursEmptyState'
import { replayVisionEmptyState } from 'products/replay_vision/frontend/emptyState/replayVisionEmptyState'
import { llmSkillsEmptyState } from 'products/skills/frontend/emptyState/llmSkillsEmptyState'
import { userInterviewsEmptyState } from 'products/user_interviews/frontend/emptyState/userInterviewsEmptyState'

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
