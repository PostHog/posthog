import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { userEvent } from 'storybook/test'

import { DashboardQuerySharingDebug } from './DashboardQuerySharingDebug'
import { summarizeSharingDebug, type DashboardSharingDebugRun } from './summarizeSharingDebug'

const run: DashboardSharingDebugRun = {
    batchId: 'example-refresh',
    status: 'complete',
    tiles: [
        { id: 1, name: 'All events' },
        { id: 2, name: 'Purchase events' },
        { id: 3, name: 'Weekly active users' },
        { id: 4, name: 'Recent events' },
    ],
    results: {
        1: {
            cached: false,
            failed: false,
            debug: {
                executions: [{ outcome: 'shared', tile_ids: [1, 2], rule: 'count_fusion', reason: '' }],
                query_count: 1,
                rows_read: 100000,
                duration_ms: 42,
                truncated: false,
            },
        },
        2: {
            cached: false,
            failed: false,
            debug: { executions: [], query_count: 0, rows_read: 0, duration_ms: 0, truncated: false },
        },
        3: {
            cached: true,
            failed: false,
            debug: { executions: [], query_count: 0, rows_read: 0, duration_ms: 0, truncated: false },
        },
        4: {
            cached: false,
            failed: false,
            debug: {
                executions: [
                    {
                        outcome: 'separate',
                        tile_ids: [4],
                        rule: '',
                        reason: 'No sharing rule supports this query shape or context.',
                    },
                ],
                query_count: 1,
                rows_read: 5000,
                duration_ms: 12,
                truncated: false,
            },
        },
    },
}

const meta: Meta<typeof DashboardQuerySharingDebug> = {
    title: 'Products/Dashboards/Query sharing debug',
    component: DashboardQuerySharingDebug,
    parameters: { featureFlags: [FEATURE_FLAGS.HOGQL_QUERY_SHARING], layout: 'fullscreen' },
    args: { dashboardName: 'Example dashboard', run, summary: summarizeSharingDebug(run) },
    decorators: [
        (Story): JSX.Element => (
            <div className="p-4">
                <Story />
            </div>
        ),
    ],
    play: async ({ canvasElement }) => {
        const toggle = canvasElement.querySelector<HTMLElement>('[data-attr="dashboard-query-sharing-debug-toggle"]')
        if (toggle) {
            await userEvent.click(toggle)
        }
    },
}
export default meta

type Story = StoryObj<typeof meta>

export const SharedAndCached: Story = {}

const partialRun: DashboardSharingDebugRun = {
    ...run,
    status: 'partial',
    results: {
        1: {
            cached: false,
            failed: false,
            debug: {
                executions: [
                    {
                        outcome: 'fallback',
                        tile_ids: [1, 2],
                        rule: 'count_fusion',
                        reason: 'Shared execution failed; each tile retries independently.',
                    },
                    { outcome: 'separate', tile_ids: [1], rule: '', reason: 'Retry after a failed shared execution.' },
                ],
                query_count: 2,
                rows_read: 120000,
                duration_ms: 60,
                truncated: false,
            },
        },
    },
}
export const PartialWithFallback: Story = { args: { run: partialRun, summary: summarizeSharingDebug(partialRun) } }

export const BeforeRefresh: Story = { args: { run: null, summary: null } }
