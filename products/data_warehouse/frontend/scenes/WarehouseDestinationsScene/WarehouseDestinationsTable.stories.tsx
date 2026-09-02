import { Meta, StoryFn } from '@storybook/react'

import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { WarehouseDestinationsTable, WarehouseDestinationsTableProps } from './WarehouseDestinationsTable'

const WAREHOUSE: ExternalDataDestinationApi = {
    id: '01a03e9c-1b76-0000-9079-2a0ee2186dea',
    type: 'PostHogWarehouse',
    name: 'PostHog warehouse',
    config: {},
    integration: null,
    is_posthog_warehouse: true,
    created_at: '2026-08-20T10:00:00Z',
    updated_at: '2026-08-25T10:00:00Z',
    created_by: null,
} as ExternalDataDestinationApi

const POSTGRES: ExternalDataDestinationApi = {
    id: '01a03e9c-1b7c-0000-71ce-5e5d7b04df8f',
    type: 'Postgres',
    name: 'Customer Postgres',
    config: { database: 'analytics', schema: 'customer_sync' },
    integration: 1,
    is_posthog_warehouse: false,
    created_at: '2026-08-24T10:00:00Z',
    updated_at: '2026-08-26T14:00:00Z',
    created_by: null,
} as ExternalDataDestinationApi

const meta: Meta<typeof WarehouseDestinationsTable> = {
    title: 'Data Warehouse/WarehouseDestinationsTable',
    component: WarehouseDestinationsTable,
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof WarehouseDestinationsTable> = (props: WarehouseDestinationsTableProps) => (
    <WarehouseDestinationsTable {...props} />
)

export const Default = Template.bind({})
Default.args = {
    destinations: [POSTGRES, WAREHOUSE],
    loading: false,
    onEdit: () => {},
    onDelete: () => {},
}

// The PostHog warehouse row is managed, so both of its actions stay disabled.
export const Deleting = Template.bind({})
Deleting.args = {
    ...Default.args,
    deletingId: POSTGRES.id,
}

export const Loading = Template.bind({})
Loading.args = {
    ...Default.args,
    destinations: [],
    loading: true,
}

export const Empty = Template.bind({})
Empty.args = {
    ...Default.args,
    destinations: [],
    emptyState: 'No destinations yet. Your sources write to the PostHog warehouse until you add one.',
}
