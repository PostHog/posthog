import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { ModelsOverviewTab } from 'scenes/models/tabs/ModelsOverviewTab'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const nodes = ['attention', 'behind'].flatMap((group) =>
    Array.from({ length: 12 }, (_, index) => ({
        id: `${group}-${index + 1}`,
        name: `${group}_model_${index + 1}`,
        type: 'matview',
        dag: 'example-dag',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        last_run_at: '2026-09-14T00:00:00Z',
        last_run_status: group === 'attention' ? 'Failed' : 'Completed',
        last_run_error: group === 'attention' ? 'Example refresh failed.' : null,
        sync_interval: '1hour',
        upstream_count: 0,
        downstream_count: 0,
    }))
)
const checks = Array.from({ length: 12 }, (_, index) => ({
    id: `check-${index + 1}`,
    name: `Example check ${index + 1}`,
    check_type: 'not_null',
    subject_type: 'view',
    subject_name: `example_view_${index + 1}`,
    subject_node_id: `attention-${index + 1}`,
    last_status: 'failed',
}))

const meta: Meta<typeof ModelsOverviewTab> = {
    title: 'Products/Data modeling/Models overview',
    component: ModelsOverviewTab,
    decorators: [mswDecorator({})],
    parameters: {
        featureFlags: [FEATURE_FLAGS.DATA_QUALITY_CHECKS],
        pageUrl: urls.models(),
        mockDate: '2026-09-15',
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/data_modeling_nodes/': { results: nodes, count: nodes.length },
                    '/api/environments/:team_id/data_modeling_edges/': { results: [], count: 0 },
                    '/api/environments/:team_id/warehouse_saved_queries/': { results: [], count: 0 },
                    '/api/projects/:team_id/data_quality_checks/': { results: checks, count: checks.length },
                    '/api/projects/:team_id/data_quality_checks/health/': [],
                },
            },
        },
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof ModelsOverviewTab>
export const Paginated: Story = {}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-128 max-w-full">
                <Story />
            </div>
        ),
    ],
}
