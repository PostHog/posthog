import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { EMPTY_PAGINATED_RESPONSE, toPaginatedResponse } from '~/mocks/handlers'

const MOCK_TOTAL_ROWS_STATS = {
    breakdown_of_rows_by_source: { Stripe: 48000, Hubspot: 25000, Postgres: 120000 },
    billing_available: true,
    billing_interval: 'month',
    billing_period_end: '2025-02-01T00:00:00Z',
    billing_period_start: '2025-01-01T00:00:00Z',
    materialized_rows_in_billing_period: 5000,
    total_rows: 193000,
    tracked_billing_rows: 193000,
    pending_billing_rows: 0,
}

const MOCK_RUNNING_ACTIVITY = [
    {
        id: 'activity-001',
        type: 'external_data',
        name: 'Stripe sync',
        status: 'Running',
        rows: 12000,
        created_at: '2025-01-27T10:00:00Z',
        finished_at: null,
        latest_error: null,
    },
]

const MOCK_COMPLETED_ACTIVITY = [
    {
        id: 'activity-002',
        type: 'external_data',
        name: 'Hubspot contacts sync',
        status: 'Completed',
        rows: 25000,
        created_at: '2025-01-27T08:00:00Z',
        finished_at: '2025-01-27T08:15:00Z',
        latest_error: null,
    },
    {
        id: 'activity-003',
        type: 'external_data',
        name: 'Postgres users sync',
        status: 'Failed',
        rows: 0,
        created_at: '2025-01-27T06:00:00Z',
        finished_at: '2025-01-27T06:02:00Z',
        latest_error: 'Connection timed out',
    },
]

const MOCK_JOB_STATS = {
    days: 7,
    cutoff_time: '2025-01-20T00:00:00Z',
    total_jobs: 42,
    successful_jobs: 38,
    failed_jobs: 4,
    external_data_jobs: { total: 30, running: 1, successful: 27, failed: 2 },
    modeling_jobs: { total: 12, running: 0, successful: 11, failed: 1 },
    breakdown: {
        Stripe: { successful: 14, failed: 1 },
        Hubspot: { successful: 13, failed: 1 },
    },
}

const MOCK_EXTERNAL_DATA_SOURCES = [
    {
        id: 'source-001',
        source_id: 'stripe-123',
        connection_id: 'conn-001',
        status: 'Running',
        source_type: 'Stripe',
        prefix: 'stripe_',
        description: 'Stripe production data',
        latest_error: null,
        last_run_at: '2025-01-27T10:00:00Z',
        schemas: [],
        sync_frequency: '1h',
        job_inputs: {},
        revenue_analytics_config: { enabled: false, include_invoiceless_charges: false },
        user_access_level: 'editor',
    },
    {
        id: 'source-002',
        source_id: 'hubspot-456',
        connection_id: 'conn-002',
        status: 'Completed',
        source_type: 'Hubspot',
        prefix: 'hubspot_',
        description: null,
        latest_error: null,
        last_run_at: '2025-01-27T08:15:00Z',
        schemas: [],
        sync_frequency: '6h',
        job_inputs: {},
        revenue_analytics_config: { enabled: false, include_invoiceless_charges: false },
        user_access_level: 'editor',
    },
]

const dataWarehouseMocks = {
    get: {
        '/api/environments/:team_id/data_warehouse/total_rows_stats/': MOCK_TOTAL_ROWS_STATS,
        '/api/environments/:team_id/data_warehouse/running_activity/': toPaginatedResponse(MOCK_RUNNING_ACTIVITY),
        '/api/environments/:team_id/data_warehouse/completed_activity/': toPaginatedResponse(MOCK_COMPLETED_ACTIVITY),
        '/api/environments/:team_id/data_warehouse/job_stats/': MOCK_JOB_STATS,
        '/api/environments/:team_id/external_data_sources/': toPaginatedResponse(MOCK_EXTERNAL_DATA_SOURCES),
    },
}

const emptyDataWarehouseMocks = {
    get: {
        '/api/environments/:team_id/data_warehouse/total_rows_stats/': {
            breakdown_of_rows_by_source: {},
            billing_available: false,
            billing_interval: 'month',
            billing_period_end: '2025-02-01T00:00:00Z',
            billing_period_start: '2025-01-01T00:00:00Z',
            materialized_rows_in_billing_period: 0,
            total_rows: 0,
            tracked_billing_rows: 0,
            pending_billing_rows: 0,
        },
        '/api/environments/:team_id/data_warehouse/running_activity/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/data_warehouse/completed_activity/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/data_warehouse/job_stats/': {
            days: 7,
            cutoff_time: '2025-01-20T00:00:00Z',
            total_jobs: 0,
            successful_jobs: 0,
            failed_jobs: 0,
            external_data_jobs: { total: 0, running: 0, successful: 0, failed: 0 },
            modeling_jobs: { total: 0, running: 0, successful: 0, failed: 0 },
            breakdown: {},
        },
        '/api/environments/:team_id/external_data_sources/': EMPTY_PAGINATED_RESPONSE,
    },
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/DataWarehouse',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2025-01-27',
        pageUrl: urls.dataWarehouse(),
        featureFlags: [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE],
    },
}
export default meta

type Story = StoryObj<typeof meta>

export const Overview: Story = {
    parameters: { pageUrl: urls.dataWarehouse() },
    decorators: [mswDecorator(dataWarehouseMocks)],
}

export const OverviewEmpty: Story = {
    parameters: { pageUrl: urls.dataWarehouse() },
    decorators: [mswDecorator(emptyDataWarehouseMocks)],
}

export const SourcesTab: Story = {
    parameters: { pageUrl: `${urls.dataWarehouse()}?tab=sources` },
    decorators: [mswDecorator(dataWarehouseMocks)],
}
