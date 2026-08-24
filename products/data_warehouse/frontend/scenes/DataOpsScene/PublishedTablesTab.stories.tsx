import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import type { PublishedTableApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { PublishedTablesTab } from './PublishedTablesTab'

const publications: PublishedTableApi[] = [
    {
        id: 'b60542fd-1786-4564-987a-07b851e29731',
        saved_query_id: '79da0bb6-0906-4187-b2ad-34fb70f45c17',
        name: 'modeled_customers',
        source_schema_name: 'analytics',
        source_table_name: 'customers',
        status: 'completed',
        last_published_at: '2026-08-24T16:30:00Z',
        last_error: null,
        row_count: 124508,
    },
    {
        id: 'fd52befe-0049-42bb-8bc3-1e75ac39df25',
        saved_query_id: '5afdd21c-b8a9-4a19-b661-eb4b3b413281',
        name: 'monthly_revenue',
        source_schema_name: 'finance',
        source_table_name: 'monthly_revenue',
        status: 'publishing',
        last_published_at: '2026-08-23T09:15:00Z',
        last_error: null,
        row_count: 36240,
    },
    {
        id: '465a10d0-22df-4ee7-ae1f-78b2c4911c95',
        saved_query_id: '7a71f8b1-ae69-4434-bfb6-9ab7b82660fc',
        name: 'account_health',
        source_schema_name: 'analytics',
        source_table_name: 'account_health',
        status: 'failed',
        last_published_at: null,
        last_error: 'The source table could not be read. Check that it still exists, then try again.',
        row_count: null,
    },
]

type Story = StoryObj<typeof PublishedTablesTab>

const meta: Meta<typeof PublishedTablesTab> = {
    title: 'Scenes-App/Data Warehouse/Data Ops/Published tables',
    component: PublishedTablesTab,
    parameters: {
        mockDate: '2026-08-24T17:00:00Z',
        viewMode: 'story',
        testOptions: {
            snapshotBrowsers: ['chromium'],
        },
    },
    render: () => {
        useStorybookMocks({
            get: {
                '/api/projects/:team_id/data_warehouse/managed-warehouse-published-tables/': [
                    200,
                    { results: publications },
                ],
                '/api/projects/:team_id/data_warehouse/managed-warehouse-modeled-tables/': [
                    200,
                    {
                        results: [
                            {
                                schema_name: 'analytics',
                                table_name: 'customers',
                                publishable: true,
                                disabled_reason: null,
                            },
                            {
                                schema_name: 'analytics',
                                table_name: 'product_usage',
                                publishable: true,
                                disabled_reason: null,
                            },
                            {
                                schema_name: 'posthog',
                                table_name: 'events',
                                publishable: false,
                                disabled_reason: "PostHog manages this schema, so you can't publish its tables.",
                            },
                        ],
                    },
                ],
            },
        })

        return (
            <div className="p-4">
                <PublishedTablesTab />
            </div>
        )
    },
}

export default meta

export const Default: Story = {}
