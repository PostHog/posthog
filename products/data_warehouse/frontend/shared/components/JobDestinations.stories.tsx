import { Meta, StoryFn } from '@storybook/react'

import { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { JobDestinations, JobDestinationsProps } from './JobDestinations'

const WAREHOUSE = {
    id: '01a03e9c-1b76-0000-9079-2a0ee2186dea',
    type: 'PostHogWarehouse',
    name: 'PostHog warehouse',
    config: {},
    integration: null,
    is_posthog_warehouse: true,
} as ExternalDataDestinationApi

const POSTGRES = {
    id: '01a03e9c-1b7c-0000-71ce-5e5d7b04df8f',
    type: 'Postgres',
    name: 'Customer Postgres',
    config: { database: 'analytics', schema: 'customer_sync' },
    integration: 1,
    is_posthog_warehouse: false,
} as ExternalDataDestinationApi

const BY_ID = { [WAREHOUSE.id]: WAREHOUSE, [POSTGRES.id]: POSTGRES }

const meta: Meta<typeof JobDestinations> = {
    title: 'Data Warehouse/JobDestinations',
    component: JobDestinations,
    tags: ['autodocs'],
}
export default meta

const Template: StoryFn<typeof JobDestinations> = (props: JobDestinationsProps) => <JobDestinations {...props} />

export const TwoDestinations = Template.bind({})
TwoDestinations.args = {
    destinationIds: [WAREHOUSE.id, POSTGRES.id],
    destinationsById: BY_ID,
}

export const WarehouseOnly = Template.bind({})
WarehouseOnly.args = {
    destinationIds: [WAREHOUSE.id],
    destinationsById: BY_ID,
}

// A run from before destinations existed recorded none, so there is nothing to show.
export const NoneRecorded = Template.bind({})
NoneRecorded.args = {
    destinationIds: [],
    destinationsById: BY_ID,
}

// Deleting a destination leaves the runs that used it pointing at nothing.
export const DestinationSinceDeleted = Template.bind({})
DestinationSinceDeleted.args = {
    destinationIds: ['01a03e9c-0000-0000-0000-000000000000'],
    destinationsById: BY_ID,
}

// Mid-fetch an unknown id is not yet a deleted one, so it stays quiet.
export const StillLoading = Template.bind({})
StillLoading.args = {
    destinationIds: [POSTGRES.id],
    destinationsById: {},
    loading: true,
}
