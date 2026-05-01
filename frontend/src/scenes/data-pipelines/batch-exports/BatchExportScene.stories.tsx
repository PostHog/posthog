import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import organizationCurrent from '~/mocks/fixtures/api/organizations/@current/@current.json'
import { ActivityScope, RawBatchExportBackfill, RawBatchExportRun } from '~/types'

import batchExports from '../__mocks__/batchExports.json'

const EXISTING_EXPORT = {
    ...batchExports.results[0],
    model: 'events',
    filters: [],
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/BatchExports',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-01-15',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/batch_exports/': batchExports,
                [`/api/environments/:team_id/batch_exports/${EXISTING_EXPORT.id}/`]: EXISTING_EXPORT,
                '/api/environments/:team_id/batch_exports/test/': { steps: [] },
                [`/api/environments/:team_id/batch_exports/${EXISTING_EXPORT.id}/runs/`]: { results: [] },
                [`/api/environments/:team_id/batch_exports/${EXISTING_EXPORT.id}/backfills/`]: { results: [] },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const NewS3Export: Story = {
    parameters: {
        pageUrl: urls.batchExportNew('s3'),
    },
}

export const ExistingBigQueryExport: Story = {
    parameters: {
        pageUrl: urls.batchExport(EXISTING_EXPORT.id),
    },
}

const MOCK_BACKFILLS: RawBatchExportBackfill[] = [
    {
        id: 'backfill-001',
        status: 'Running',
        created_at: '2024-01-15T10:00:00Z',
        start_at: '2024-01-10T00:00:00Z',
        end_at: '2024-01-15T00:00:00Z',
        last_updated_at: '2024-01-15T10:05:00Z',
        total_records_count: 142500,
        progress: { progress: 0.35, finished_runs: 42, total_runs: 120 },
    },
    {
        id: 'backfill-002',
        status: 'Completed',
        created_at: '2024-01-14T08:00:00Z',
        finished_at: '2024-01-14T09:30:00Z',
        start_at: '2024-01-01T00:00:00Z',
        end_at: '2024-01-10T00:00:00Z',
        last_updated_at: '2024-01-14T09:30:00Z',
        total_records_count: 89200,
        progress: { progress: 1, finished_runs: 216, total_runs: 216 },
    },
    {
        id: 'backfill-003',
        status: 'Failed',
        created_at: '2024-01-13T12:00:00Z',
        finished_at: '2024-01-13T12:15:00Z',
        start_at: '2023-12-01T00:00:00Z',
        end_at: '2024-01-01T00:00:00Z',
        last_updated_at: '2024-01-13T12:15:00Z',
        total_records_count: 350000,
        progress: { progress: 0.05, finished_runs: 12, total_runs: 240 },
    },
    {
        id: 'backfill-004',
        status: 'Starting',
        created_at: '2024-01-15T11:00:00Z',
        start_at: '2024-01-14T00:00:00Z',
        end_at: '2024-01-15T00:00:00Z',
        last_updated_at: '2024-01-15T11:00:00Z',
    },
]

export const BackfillsWithEstimates: Story = {
    parameters: {
        pageUrl: `${urls.batchExport(EXISTING_EXPORT.id)}?tab=backfills`,
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/batch_exports/': batchExports,
                [`/api/environments/:team_id/batch_exports/${EXISTING_EXPORT.id}/`]: EXISTING_EXPORT,
                '/api/environments/:team_id/batch_exports/test/': { steps: [] },
                [`/api/environments/:team_id/batch_exports/${EXISTING_EXPORT.id}/runs/`]: { results: [] },
                [`/api/environments/:team_id/batch_exports/${EXISTING_EXPORT.id}/backfills/`]: {
                    results: MOCK_BACKFILLS,
                    next: null,
                },
            },
        }),
    ],
}

export const BackfillsEmpty: Story = {
    parameters: {
        pageUrl: `${urls.batchExport(EXISTING_EXPORT.id)}?tab=backfills`,
    },
}

const MOCK_RUNS: RawBatchExportRun[] = [
    {
        id: 'run-001',
        status: 'Completed',
        created_at: '2024-01-15T10:01:00Z',
        data_interval_start: '2024-01-15T09:00:00Z',
        data_interval_end: '2024-01-15T10:00:00Z',
        last_updated_at: '2024-01-15T10:03:00Z',
        records_completed: 48230,
        bytes_exported: 12_582_912,
    },
    {
        id: 'run-002',
        status: 'Running',
        created_at: '2024-01-15T11:01:00Z',
        data_interval_start: '2024-01-15T10:00:00Z',
        data_interval_end: '2024-01-15T11:00:00Z',
        last_updated_at: '2024-01-15T11:02:00Z',
    },
    {
        id: 'run-003',
        status: 'Failed',
        created_at: '2024-01-15T09:01:00Z',
        data_interval_start: '2024-01-15T08:00:00Z',
        data_interval_end: '2024-01-15T09:00:00Z',
        last_updated_at: '2024-01-15T09:04:00Z',
        latest_error:
            'NotFound: 404 POST https://bigquery.googleapis.com/bigquery/v2/projects/posthog-301601/datasets/BatchExports/tables?prettyPrint=false: Not found: Dataset posthog-301601:BatchExports',
    },
    {
        id: 'run-004',
        status: 'Starting',
        created_at: '2024-01-15T12:00:30Z',
        data_interval_start: '2024-01-15T11:00:00Z',
        data_interval_end: '2024-01-15T12:00:00Z',
        last_updated_at: '2024-01-15T12:00:30Z',
    },
    {
        id: 'run-005',
        status: 'Cancelled',
        created_at: '2024-01-15T08:01:00Z',
        data_interval_start: '2024-01-15T07:00:00Z',
        data_interval_end: '2024-01-15T08:00:00Z',
        last_updated_at: '2024-01-15T08:02:00Z',
    },
]

export const RunsWithData: Story = {
    parameters: {
        pageUrl: `${urls.batchExport(EXISTING_EXPORT.id)}?tab=runs`,
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/batch_exports/': batchExports,
                [`/api/environments/:team_id/batch_exports/${EXISTING_EXPORT.id}/`]: EXISTING_EXPORT,
                '/api/environments/:team_id/batch_exports/test/': { steps: [] },
                [`/api/environments/:team_id/batch_exports/${EXISTING_EXPORT.id}/runs/`]: {
                    results: MOCK_RUNS,
                    next: null,
                },
                [`/api/environments/:team_id/batch_exports/${EXISTING_EXPORT.id}/backfills/`]: { results: [] },
            },
        }),
    ],
}

export const RunsEmpty: Story = {
    parameters: {
        pageUrl: `${urls.batchExport(EXISTING_EXPORT.id)}?tab=runs`,
    },
}

const MOCK_LOG_RESULTS = {
    results: [
        [
            'run-aaa-bbb-ccc',
            '2024-01-15 10:00:00.000001',
            'INFO',
            'Batch exporting range 2024-01-15T09:00:00Z - 2024-01-15T10:00:00Z to BigQuery: posthog-301601.BatchExports.events',
        ],
        [
            'run-aaa-bbb-ccc',
            '2024-01-15 10:00:02.000003',
            'INFO',
            'Batch export for range 2024-01-15T09:00:00Z - 2024-01-15T10:00:00Z finished successfully with 48230 records exported',
        ],
        [
            'run-ddd-eee-fff',
            '2024-01-15 10:05:00.000001',
            'INFO',
            'Batch exporting range 2024-01-15T10:00:00Z - 2024-01-15T11:00:00Z to BigQuery: posthog-301601.BatchExports.events',
        ],
        ['run-ddd-eee-fff', '2024-01-15 10:05:01.000002', 'WARN', 'Retrying after transient error'],
        [
            'run-ddd-eee-fff',
            '2024-01-15 10:05:05.000003',
            'ERROR',
            'Batch export for range 2024-01-15T10:00:00Z - 2024-01-15T11:00:00Z failed with a non-recoverable error: NotFound: 404 POST https://bigquery.googleapis.com/bigquery/v2/projects/posthog-301601/datasets/BatchExports/tables?prettyPrint=false: Not found: Dataset posthog-301601:BatchExports',
        ],
    ],
}

export const Logs: Story = {
    parameters: {
        pageUrl: `${urls.batchExport(EXISTING_EXPORT.id)}?tab=logs`,
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/HogQLQuery/': MOCK_LOG_RESULTS,
            },
        }),
    ],
}

export const Metrics: Story = {
    parameters: {
        pageUrl: `${urls.batchExport(EXISTING_EXPORT.id)}?tab=metrics`,
    },
}

const EXPORT_DETAIL_NAME = `'${EXISTING_EXPORT.name}' (${EXISTING_EXPORT.destination.type})`

const MOCK_ACTIVITY_LOGS = {
    results: [
        {
            id: 'activity-005',
            user: { first_name: 'Max', last_name: 'Hog', email: 'max@posthog.com' },
            activity: 'updated',
            created_at: '2024-01-14T18:00:00Z',
            scope: ActivityScope.BATCH_EXPORT,
            item_id: EXISTING_EXPORT.id,
            detail: {
                name: EXPORT_DETAIL_NAME,
                merge: null,
                trigger: null,
                changes: [
                    { type: 'BatchExport', action: 'changed', field: 'interval_offset', before: 0, after: 7200 },
                    { type: 'BatchExport', action: 'changed', field: 'timezone', before: 'UTC', after: 'US/Pacific' },
                ],
            },
        },
        {
            id: 'activity-004',
            user: { first_name: 'Max', last_name: 'Hog', email: 'max@posthog.com' },
            activity: 'updated',
            created_at: '2024-01-14T16:00:00Z',
            scope: ActivityScope.BATCH_EXPORT,
            item_id: EXISTING_EXPORT.id,
            detail: {
                name: EXPORT_DETAIL_NAME,
                merge: null,
                trigger: null,
                changes: [{ type: 'BatchExport', action: 'changed', field: 'enabled', before: true, after: false }],
            },
        },
        {
            id: 'activity-003',
            user: { first_name: 'Mix', last_name: 'Hog', email: 'mix@posthog.com' },
            activity: 'updated',
            created_at: '2024-01-14T14:00:00Z',
            scope: ActivityScope.BATCH_EXPORT,
            item_id: EXISTING_EXPORT.id,
            detail: {
                name: EXPORT_DETAIL_NAME,
                merge: null,
                trigger: null,
                changes: [
                    {
                        type: 'BatchExport',
                        action: 'changed',
                        field: 'name',
                        before: 'Old Export Name',
                        after: EXISTING_EXPORT.name,
                    },
                ],
            },
        },
        {
            id: 'activity-002',
            user: { first_name: 'Mix', last_name: 'Hog', email: 'mix@posthog.com' },
            activity: 'updated',
            created_at: '2024-01-14T12:00:00Z',
            scope: ActivityScope.BATCH_EXPORT,
            item_id: EXISTING_EXPORT.id,
            detail: {
                name: `'Old Export Name' (${EXISTING_EXPORT.destination.type})`,
                merge: null,
                trigger: null,
                changes: [{ type: 'BatchExport', action: 'changed', field: 'interval', before: 'hour', after: 'day' }],
            },
        },
        {
            id: 'activity-001',
            user: { first_name: 'Mix', last_name: 'Hog', email: 'mix@posthog.com' },
            activity: 'created',
            created_at: '2024-01-14T10:00:00Z',
            scope: ActivityScope.BATCH_EXPORT,
            item_id: EXISTING_EXPORT.id,
            detail: {
                name: `'Old Export Name' (${EXISTING_EXPORT.destination.type})`,
                merge: null,
                trigger: null,
                changes: null,
            },
        },
    ],
    total_count: 5,
}

export const HistoryWithActivity: Story = {
    parameters: {
        pageUrl: `${urls.batchExport(EXISTING_EXPORT.id)}?tab=history`,
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/users/@me': () => [
                    200,
                    {
                        email: 'test@posthog.com',
                        first_name: 'Test',
                        organization: {
                            ...organizationCurrent,
                            available_product_features: [{ key: 'audit_logs', name: 'Audit logs' }],
                        },
                    },
                ],
                '/api/projects/:team_id/activity_log/': MOCK_ACTIVITY_LOGS,
            },
        }),
    ],
}

export const HistoryEmpty: Story = {
    parameters: {
        pageUrl: `${urls.batchExport(EXISTING_EXPORT.id)}?tab=history`,
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/users/@me': () => [
                    200,
                    {
                        email: 'test@posthog.com',
                        first_name: 'Test',
                        organization: {
                            ...organizationCurrent,
                            available_product_features: [{ key: 'audit_logs', name: 'Audit logs' }],
                        },
                    },
                ],
                '/api/projects/:team_id/activity_log/': { results: [], total_count: 0 },
            },
        }),
    ],
}
