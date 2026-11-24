import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { userEvent } from 'storybook/test'

import type {
    ManagedWarehouseDatasetStatusApi,
    ManagedWarehouseDataStatusResponseApi,
    ManagedWarehouseLandingCountsApi,
    ManagedWarehouseSourceSummaryApi,
    ManagedWarehouseSourceTableStatusApi,
} from '../../generated/api.schemas'
import { WarehousePostHogDataScene } from './WarehousePostHogDataScene'
import { WarehouseSourceDataScene } from './WarehouseSourceDataScene'

// Every date is written relative to this one, which `mockDate` pins as the clock.
const NOW = Date.parse('2026-11-24T12:00:00Z')
const hoursAgo = (hours: number): string => new Date(NOW - hours * 3_600_000).toISOString()
const daysAgo = (days: number): string => hoursAgo(days * 24)

const READY_WAREHOUSE = {
    org_id: 'org-1',
    state: 'ready',
    status_message: 'Ready',
    s3_state: 'ready',
    metadata_store_state: 'ready',
    identity_state: 'ready',
    secrets_state: 'ready',
    ready_at: daysAgo(30),
    failed_at: null,
    trino: { state: 'ready', hoglake: false, connection: null },
    has_backfill: true,
    table_suffix: null,
    team_onboarded: true,
    schema_name: 'main',
}

function dataset(
    name: 'events' | 'persons',
    overrides: Partial<ManagedWarehouseDatasetStatusApi>
): ManagedWarehouseDatasetStatusApi {
    return {
        dataset: name,
        readiness_state: 'up_to_date',
        detail: '',
        completed_partitions: 30,
        total_partitions: 30,
        current_partition: null,
        last_updated_at: hoursAgo(1),
        landing_state: 'in_sync',
        failed_partitions: 0,
        last_error: null,
        last_completed_at: hoursAgo(1),
        latest_day_loaded: '2026-11-23',
        ...overrides,
    }
}

function source(
    id: string,
    name: string,
    type: string,
    counts: Partial<ManagedWarehouseLandingCountsApi>,
    overrides: Partial<ManagedWarehouseSourceSummaryApi>
): ManagedWarehouseSourceSummaryApi {
    const landing_counts = { in_sync: 0, behind: 0, failing: 0, not_in_warehouse: 0, paused: 0, ...counts }
    const total = Object.values(landing_counts).reduce((sum, count) => sum + count, 0)
    return {
        source_id: id,
        source_name: name,
        source_type: type,
        readiness_state: 'up_to_date',
        detail: '',
        total_schemas: total,
        applied_schemas: landing_counts.in_sync,
        last_applied_at: hoursAgo(1),
        last_synced_at: hoursAgo(1),
        landing_state: 'in_sync',
        landing_counts,
        pending_since: null,
        sync_failed_schemas: 0,
        ...overrides,
    }
}

function status(
    events: ManagedWarehouseDatasetStatusApi,
    persons: ManagedWarehouseDatasetStatusApi,
    sources: ManagedWarehouseSourceSummaryApi[]
): ManagedWarehouseDataStatusResponseApi {
    return {
        overall_readiness_state: 'up_to_date',
        events,
        persons,
        sources: { readiness_state: 'up_to_date', detail: '', sources },
        generated_at: hoursAgo(0.05),
    } as ManagedWarehouseDataStatusResponseApi
}

const HEALTHY = status(dataset('events', {}), dataset('persons', {}), [
    source('src-stripe', 'Stripe', 'Stripe', { in_sync: 8 }, {}),
    source('src-postgres', 'Production replica', 'Postgres', { in_sync: 14 }, {}),
])

const MIXED = status(
    dataset('events', {
        readiness_state: 'backfilling',
        landing_state: 'behind',
        completed_partitions: 12,
        total_partitions: 14,
        current_partition: '2026-11-13',
        latest_day_loaded: '2026-11-12',
        last_completed_at: hoursAgo(2),
    }),
    dataset('persons', {}),
    [
        source(
            'src-stripe',
            'Stripe',
            'Stripe',
            { in_sync: 6, failing: 2 },
            { landing_state: 'failing', last_applied_at: hoursAgo(30), pending_since: hoursAgo(5) }
        ),
        source(
            'src-postgres',
            'Production replica',
            'Postgres',
            { in_sync: 10, behind: 3, paused: 1 },
            { landing_state: 'behind', pending_since: hoursAgo(2), sync_failed_schemas: 1 }
        ),
        source(
            'src-hubspot',
            'Marketing CRM',
            'Hubspot',
            { not_in_warehouse: 4 },
            { landing_state: 'not_in_warehouse', last_applied_at: null, last_synced_at: null }
        ),
        source('src-zendesk', 'Support desk', 'Zendesk', { in_sync: 5 }, {}),
    ]
)

const EMPTY = status(
    dataset('events', {
        readiness_state: 'not_configured',
        landing_state: 'not_in_warehouse',
        completed_partitions: 0,
        total_partitions: null,
        last_updated_at: null,
        last_completed_at: null,
        latest_day_loaded: null,
    }),
    dataset('persons', {
        readiness_state: 'not_configured',
        landing_state: 'not_in_warehouse',
        completed_partitions: 0,
        total_partitions: null,
        last_updated_at: null,
        last_completed_at: null,
        latest_day_loaded: null,
    }),
    []
)

function schema(
    id: string,
    name: string,
    overrides: Partial<ManagedWarehouseSourceTableStatusApi>
): ManagedWarehouseSourceTableStatusApi {
    return {
        schema_id: id,
        source_id: 'src-stripe',
        source_name: 'Stripe',
        source_type: 'Stripe',
        table_name: name,
        readiness_state: 'up_to_date',
        detail: '',
        workflow_type: 'copy',
        workflow_status: 'completed',
        workflow_started_at: hoursAgo(1),
        applied: true,
        last_applied_at: hoursAgo(1),
        last_synced_at: hoursAgo(1),
        landing_state: 'in_sync',
        pending_since: null,
        workflow_finished_at: hoursAgo(1),
        workflow_error: null,
        sync_status: 'Completed',
        sync_error: null,
        last_sync_rows: 1200,
        ...overrides,
    }
}

const STRIPE_SCHEMAS = [
    schema('sch-charges', 'stripe_charges', {
        landing_state: 'failing',
        workflow_status: 'failed',
        workflow_error: 'Copy failed: the destination rejected the file because its schema changed',
        pending_since: hoursAgo(5),
        last_applied_at: hoursAgo(30),
        last_sync_rows: 4300,
    }),
    schema('sch-invoices', 'stripe_invoices', {
        landing_state: 'behind',
        workflow_status: 'running',
        pending_since: hoursAgo(1),
        sync_status: 'Completed',
        last_sync_rows: 310,
    }),
    schema('sch-customers', 'stripe_customers', {}),
]

function mocks(
    dataStatus: ManagedWarehouseDataStatusResponseApi | 500,
    options: { schemas?: ManagedWarehouseSourceTableStatusApi[] } = {}
): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/api/projects/:team_id/data_warehouse/warehouse_status/': READY_WAREHOUSE,
            '/api/projects/:team_id/data_warehouse/managed-warehouse-data-status/':
                dataStatus === 500 ? (): [number, unknown] => [500, { detail: 'Server error' }] : dataStatus,
            '/api/projects/:team_id/data_warehouse/managed-warehouse-source-schemas/': {
                schemas: options.schemas ?? [],
            },
        },
    })
}

const meta: Meta = {
    title: 'Scenes-App/Data Warehouse/Warehouse data',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-11-24T12:00:00Z',
        featureFlags: [FEATURE_FLAGS.MANAGED_WAREHOUSE_CONSOLE],
    },
}
export default meta

type Story = StoryObj<typeof meta>

const POSTHOG_DATA = {
    render: () => <WarehousePostHogDataScene />,
    parameters: {
        pageUrl: urls.warehousePostHogData(),
        testOptions: { waitForSelector: '[data-attr="warehouse-pipeline-health-events"]' },
    },
} satisfies Story

const SOURCE_DATA = {
    render: () => <WarehouseSourceDataScene />,
    parameters: {
        pageUrl: urls.warehouseSourceData(),
        testOptions: { waitForSelector: '[data-attr="warehouse-pipeline-health-sources"]' },
    },
} satisfies Story

export const PostHogData: Story = { ...POSTHOG_DATA, decorators: [mocks(MIXED)] }

export const PostHogDataBackfillOff: Story = { ...POSTHOG_DATA, decorators: [mocks(EMPTY)] }

export const SourceData: Story = { ...SOURCE_DATA, decorators: [mocks(MIXED)] }

export const SourceDataAllInSync: Story = { ...SOURCE_DATA, decorators: [mocks(HEALTHY)] }

export const SourceDataEmpty: Story = { ...SOURCE_DATA, decorators: [mocks(EMPTY)] }

export const SourceDataWithTablesOpen: Story = {
    ...SOURCE_DATA,
    decorators: [mocks(MIXED, { schemas: STRIPE_SCHEMAS })],
    parameters: {
        pageUrl: urls.warehouseSourceData(),
        testOptions: { waitForSelector: '[data-attr="warehouse-pipeline-health-schema-link"]' },
    },
    play: async ({ canvasElement }): Promise<void> => {
        const toggle = await waitFor(
            () => {
                const button = canvasElement.querySelector<HTMLElement>(
                    '[data-attr="warehouse-pipeline-health-source-toggle"]'
                )
                if (!button) {
                    throw new Error('Source toggle not yet rendered')
                }
                return button
            },
            { timeout: 2000 }
        )
        await userEvent.click(toggle)
    },
}

export const StatusLoadError: Story = {
    ...POSTHOG_DATA,
    decorators: [mocks(500)],
    parameters: {
        pageUrl: urls.warehousePostHogData(),
        testOptions: { waitForSelector: '[data-attr="warehouse-pipeline-health-retry"]' },
    },
}
