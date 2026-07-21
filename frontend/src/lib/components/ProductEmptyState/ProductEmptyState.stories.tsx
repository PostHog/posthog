import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { mcpAnalyticsEmptyState } from 'products/mcp_analytics/frontend/emptyState/mcpAnalyticsEmptyState'

import { ProductEmptyState } from './ProductEmptyState'

// Renders each adopting product's real empty-state config (the exact object its scene
// gate uses), so storybook and visual regression cover the shipped surface rather than
// a demo. As more products adopt the platform, add their configs as stories here.

/**
 * The MCP status indicator mounts the product's onboarding logic, which polls a
 * signal query and registers a product intent - answer both so the indicator
 * matches the story's mode. Signal row shape:
 * [has_initialize, tool_calls_total, tool_calls_7d, first_call_at]
 */
function mcpAnalyticsMocks(hasInitialize: boolean): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        post: {
            '/api/environments/:team_id/query/:kind': [
                200,
                { results: [[hasInitialize, 0, 0, '1970-01-01T00:00:00Z']] },
            ],
        },
        patch: {
            '/api/environments/:team_id/add_product_intent': [200, {}],
        },
    })
}

const meta: Meta<typeof ProductEmptyState> = {
    title: 'Components/Product Empty State',
    component: ProductEmptyState,
}
export default meta

type Story = StoryObj<typeof ProductEmptyState>

export const MCPAnalyticsNeedsSetup: Story = {
    args: { config: mcpAnalyticsEmptyState.config, mode: 'needs-setup' },
    decorators: [mcpAnalyticsMocks(false)],
}

export const MCPAnalyticsWaitingForData: Story = {
    args: { config: mcpAnalyticsEmptyState.config, mode: 'waiting-for-data' },
    decorators: [mcpAnalyticsMocks(true)],
}

// No wizard configured (the self-hosted rendering, where the terminal hides and the
// manual setup path is promoted).
export const MCPAnalyticsWithoutWizard: Story = {
    args: {
        config: { ...mcpAnalyticsEmptyState.config, wizard: undefined },
        mode: 'needs-setup',
    },
    decorators: [mcpAnalyticsMocks(false)],
}
