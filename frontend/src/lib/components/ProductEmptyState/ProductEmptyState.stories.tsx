import { Meta } from '@storybook/react'

import type { Mocks } from '~/mocks/utils'

import { mcpAnalyticsEmptyState } from 'products/mcp_analytics/frontend/emptyState/mcpAnalyticsEmptyState'

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
