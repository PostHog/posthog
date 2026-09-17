import type { Meta, StoryObj } from '@storybook/react'

import { ViewsTab } from 'scenes/data-warehouse/scene/ViewsTab'
import { viewsTabLogic } from 'scenes/data-warehouse/scene/viewsTabLogic'

import { mswDecorator } from '~/mocks/browser'

const createdBy = { id: 1, uuid: 'example-user', first_name: 'Alex', email: 'alex@example.com' }
const endpoint = {
    id: 'weekly-endpoint',
    name: 'weekly_activity',
    current_version: 2,
    versions_count: 2,
    is_materialized: false,
    created_at: '2026-09-01T12:00:00Z',
    created_by: createdBy,
    model_unavailable_reason: null,
}
const views = [
    {
        id: 'view-orders',
        name: 'orders_by_week',
        columns: [],
        managed_viewset_kind: null,
        origin: 'data_warehouse',
        is_materialized: false,
        created_by: createdBy,
        created_at: '2026-09-01T12:00:00Z',
    },
    ...[2, 1].map((version) => ({
        id: `endpoint-version-${version}`,
        name: `weekly_activity_v${version}`,
        columns: [],
        managed_viewset_kind: null,
        origin: 'endpoint',
        endpoint: { name: 'weekly_activity', version, is_current: version === 2 },
        is_materialized: version === 1,
        status: version === 1 ? 'Completed' : null,
        created_by: createdBy,
        created_at: '2026-09-01T12:00:00Z',
    })),
]

const meta: Meta<typeof ViewsTab> = {
    title: 'Products/Data modeling/Models list',
    component: ViewsTab,
    decorators: [
        (Story) => (
            <div className="@container/main-content">
                <Story />
            </div>
        ),
        mswDecorator({
            get: {
                '/api/environments/:team_id/warehouse_saved_queries/': { results: views, count: views.length },
                '/api/projects/:team_id/endpoints/': { results: [endpoint], count: 1 },
                '/api/projects/:team_id/endpoints/:name/versions/': {
                    results: [2, 1].map((version) => ({ ...endpoint, version, is_materialized: version === 1 })),
                    count: 2,
                },
                '/api/environments/:team_id/data_modeling_nodes/': { results: [], count: 0 },
                '/api/environments/:team_id/data_modeling_edges/': { results: [], count: 0 },
                '/api/environments/:team_id/warehouse_saved_queries/:id/run_history/': { run_history: [] },
            },
            post: { '/api/environments/:team_id/query/': { tables: {} } },
        }),
    ],
    parameters: { mockDate: '2026-09-17', testOptions: { snapshotBrowsers: ['chromium'] } },
}
export default meta

type Story = StoryObj<typeof ViewsTab>
export const PublishedEndpoint: Story = {}
export const ExpandedEndpoint: Story = {
    play: () => {
        viewsTabLogic.actions.toggleEndpointExpanded('weekly_activity')
    },
}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="@container/main-content w-128">
                <Story />
            </div>
        ),
    ],
}
export const UnavailableModel: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/endpoints/': {
                    results: [
                        {
                            ...endpoint,
                            current_version: 3,
                            versions_count: 3,
                            model_unavailable_reason:
                                'Lineage and data quality are not available for this insight configuration.',
                        },
                    ],
                    count: 1,
                },
            },
        }),
    ],
}
