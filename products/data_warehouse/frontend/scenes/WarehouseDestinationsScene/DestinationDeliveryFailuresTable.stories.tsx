import { Meta, StoryFn } from '@storybook/react'

import { DestinationDeliveryFailureApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import {
    DestinationDeliveryFailuresTable,
    DestinationDeliveryFailuresTableProps,
} from './DestinationDeliveryFailuresTable'

const TRANSIENT_FAILURE: DestinationDeliveryFailureApi = {
    job_id: '01a03e9c-1b76-0000-9079-2a0ee2186dea',
    source_id: '01a03e9c-1b7c-0000-71ce-5e5d7b04df8f',
    source_name: 'Stripe',
    source_type: 'Stripe',
    schema_id: '01a03e9c-1b81-0000-4c2a-8f1d3e6b7a90',
    schema_name: 'charges',
    error: 'Timed-out while trying to connect for 5 attempts. Check that the host accepts connections from PostHog.',
    is_configuration_error: false,
    created_at: '2026-11-17T09:00:00Z',
    finished_at: '2026-11-17T09:04:00Z',
    workflow_run_id: 'run-1',
}

const CONFIGURATION_FAILURE: DestinationDeliveryFailureApi = {
    ...TRANSIENT_FAILURE,
    job_id: '01a03e9c-1b86-0000-1d2e-3f4a5b6c7d8e',
    schema_id: '01a03e9c-1b8b-0000-9a8b-7c6d5e4f3a2b',
    schema_name: 'invoices',
    error: 'Destination configuration error. The user lacks privileges to create tables in the schema.',
    is_configuration_error: true,
    created_at: '2026-11-17T08:00:00Z',
    finished_at: '2026-11-17T08:01:00Z',
}

const meta: Meta<typeof DestinationDeliveryFailuresTable> = {
    title: 'Data Warehouse/DestinationDeliveryFailuresTable',
    component: DestinationDeliveryFailuresTable,
    parameters: {
        mockDate: '2026-11-17T12:00:00Z',
        testOptions: { snapshotBrowsers: [] },
    },
}
export default meta

const Template: StoryFn<typeof DestinationDeliveryFailuresTable> = (props: DestinationDeliveryFailuresTableProps) => (
    <DestinationDeliveryFailuresTable {...props} />
)

export const Failures = Template.bind({})
Failures.args = {
    failures: [TRANSIENT_FAILURE, CONFIGURATION_FAILURE],
    loading: false,
    windowDays: 14,
}

export const NoFailures = Template.bind({})
NoFailures.args = {
    failures: [],
    loading: false,
    windowDays: 14,
}
