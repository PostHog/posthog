import type { Meta, StoryObj } from '@storybook/react'
import { fireEvent, within } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { ViewsTab } from 'scenes/data-warehouse/scene/ViewsTab'

import { mswDecorator } from '~/mocks/browser'

const meta: Meta<typeof ViewsTab> = {
    title: 'Products/Data modeling/Views list',
    component: ViewsTab,
    decorators: [mswDecorator({})],
    parameters: {
        featureFlags: [FEATURE_FLAGS.HOGQL_WAREHOUSE_ACCESS_CONTROL],
        mockDate: '2026-09-15',
        msw: {
            mocks: {
                get: {
                    '/api/environments/:team_id/warehouse_saved_queries/': {
                        count: 1,
                        results: [
                            {
                                id: 'example-view',
                                name: 'example_summary',
                                columns: [],
                                is_materialized: true,
                                created_at: '2026-01-01T00:00:00Z',
                                managed_viewset_kind: null,
                                user_access_level: 'editor',
                            },
                        ],
                    },
                    '/api/environments/:team_id/data_modeling_nodes/': { count: 0, results: [] },
                    '/api/environments/:team_id/data_modeling_edges/': { count: 0, results: [] },
                    '/api/environments/:team_id/warehouse_saved_queries/:id/run_history/': { run_history: [] },
                },
                post: { '/api/environments/:team_id/query/': { tables: {} } },
            },
        },
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof ViewsTab>
export const Actions: Story = {
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await canvas.findByText('example_summary')
        fireEvent.click(canvas.getByRole('button', { name: 'more' }))
        await within(document.body).findByText('Access control')
    },
}
