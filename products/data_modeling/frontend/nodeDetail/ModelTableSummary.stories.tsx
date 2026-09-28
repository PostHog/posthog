import type { Meta, StoryObj } from '@storybook/react'

import type { ExternalDataSchemaWithSource, ExternalDataSource } from '~/types'

import { ModelTableSummary } from './ModelTableSummary'

const meta: Meta<typeof ModelTableSummary> = {
    title: 'Products/Data modeling/Model table summary',
    component: ModelTableSummary,
    decorators: [
        (Story) => (
            <div className="w-[56rem]">
                <Story />
            </div>
        ),
    ],
    args: {
        id: 'node-1',
        node: { origin: 'posthog', downstream_count: 3 },
        table: null,
        source: null,
        schema: null,
        loading: false,
        error: false,
        accessDenied: false,
        onRetry: () => undefined,
    },
    parameters: { testOptions: { snapshotBrowsers: ['chromium'] } },
}
export default meta

type Story = StoryObj<typeof ModelTableSummary>

export const PostHog: Story = {}

export const SelfManaged: Story = {
    args: {
        node: { origin: 'warehouse', downstream_count: 0 },
        table: {
            id: 'table-1',
            name: 'orders',
            format: 'Parquet',
            url_pattern: 'https://example.com/orders/*.parquet',
            credential: null,
        },
    },
}

export const Synced: Story = {
    args: {
        node: { origin: 'warehouse', downstream_count: 2 },
        table: {
            id: 'table-1',
            name: 'orders',
            format: 'Parquet',
            url_pattern: '',
            credential: null,
        },
        source: {
            id: 'source-1',
            source_type: 'Postgres',
            access_method: 'warehouse',
        } as ExternalDataSource,
        schema: {
            id: 'schema-1',
            name: 'orders',
            label: 'Orders',
            should_sync: true,
            status: 'Completed',
            latest_error: null,
            last_synced_at: '2026-09-19T10:00:00Z',
            sync_type: 'incremental',
            sync_frequency: '24hour',
        } as unknown as ExternalDataSchemaWithSource,
    },
}

export const Loading: Story = {
    args: {
        node: { origin: 'warehouse', downstream_count: 0 },
        loading: true,
    },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}

export const Error: Story = {
    args: {
        node: { origin: 'warehouse', downstream_count: 0 },
        error: true,
    },
}
