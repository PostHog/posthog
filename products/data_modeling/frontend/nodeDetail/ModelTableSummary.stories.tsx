import type { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { ExternalDataSchemaStatus } from '~/types'

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
        table: { format: 'Parquet' },
    },
}

export const Synced: Story = {
    args: {
        node: { origin: 'warehouse', downstream_count: 2 },
        table: { format: 'Parquet' },
        source: { id: 'source-1', source_type: 'Postgres', access_method: 'warehouse' },
        schema: {
            id: 'schema-1',
            status: ExternalDataSchemaStatus.Completed,
            latest_error: null,
            last_synced_at: dayjs('2026-09-19T10:00:00Z'),
            sync_type: 'incremental',
            sync_frequency: '24hour',
        },
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
