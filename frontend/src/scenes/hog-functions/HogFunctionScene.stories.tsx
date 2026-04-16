import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { RawBatchExportBackfill } from '~/types'

const MOCK_HOG_FUNCTION_ID = '0196b144-1f82-0000-0d0d-a01de54d674d'
const MOCK_BATCH_EXPORT_ID = '018cf79f-a9e5-0001-cd6a-edc4886d939d'

const MOCK_HOG_FUNCTION = {
    id: MOCK_HOG_FUNCTION_ID,
    type: 'destination',
    kind: null,
    name: 'HTTP Webhook',
    description: 'Sends a webhook templated by the incoming event data',
    enabled: true,
    deleted: false,
    hog: "let res := fetch(inputs.url, {\n  'headers': inputs.headers,\n  'body': inputs.body,\n  'method': inputs.method\n});",
    bytecode: [],
    inputs_schema: [
        { key: 'url', type: 'string', label: 'Webhook URL', secret: false, required: true },
        { key: 'method', type: 'choice', label: 'Method', secret: false, required: false, default: 'POST' },
    ],
    inputs: {
        url: { value: 'https://example.com/webhook' },
        method: { value: 'POST' },
    },
    filters: {},
    icon_url: null,
    template: { id: 'template-webhook', name: 'HTTP Webhook' },
    status: { state: 0, ratings: [], states: [] },
    created_at: '2024-01-01T00:00:00Z',
    created_by: {
        id: 1,
        uuid: 'user-001',
        distinct_id: 'user-001',
        first_name: 'Test',
        last_name: '',
        email: 'test@posthog.com',
        is_email_verified: true,
    },
    updated_at: '2024-01-15T00:00:00Z',
    configuration: {},
    batch_export_id: MOCK_BATCH_EXPORT_ID,
}

const MOCK_BATCH_EXPORT = {
    id: MOCK_BATCH_EXPORT_ID,
    team_id: 1,
    name: 'HTTP Webhook',
    destination: {
        type: 'Workflows',
        config: { hog_function_id: MOCK_HOG_FUNCTION_ID },
    },
    interval: 'day',
    paused: true,
    created_at: '2024-01-01T00:00:00Z',
    last_updated_at: '2024-01-15T00:00:00Z',
    start_at: null,
    end_at: null,
    model: 'events',
    filters: [],
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
]

const commonMocks = {
    get: {
        [`/api/environments/:team_id/hog_functions/${MOCK_HOG_FUNCTION_ID}/`]: MOCK_HOG_FUNCTION,
        '/api/environments/:team_id/hog_functions/': { count: 1, results: [MOCK_HOG_FUNCTION], next: null },
        [`/api/environments/:team_id/batch_exports/${MOCK_BATCH_EXPORT_ID}/`]: MOCK_BATCH_EXPORT,
        [`/api/environments/:team_id/batch_exports/${MOCK_BATCH_EXPORT_ID}/runs/`]: { results: [], next: null },
    },
    post: {
        // Fallback in case enableBackfills is triggered (e.g. for hog functions without batch_export_id)
        [`/api/environments/:team_id/hog_functions/${MOCK_HOG_FUNCTION_ID}/enable_backfills/`]: {
            batch_export_id: MOCK_BATCH_EXPORT_ID,
        },
    },
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/HogFunctions/Destination',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-01-15',
        featureFlags: [FEATURE_FLAGS.BACKFILL_WORKFLOWS_DESTINATION],
    },
    decorators: [
        mswDecorator({
            ...commonMocks,
            get: {
                ...commonMocks.get,
                [`/api/environments/:team_id/batch_exports/${MOCK_BATCH_EXPORT_ID}/backfills/`]: {
                    results: [],
                    next: null,
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const BackfillsWithData: Story = {
    parameters: {
        pageUrl: urls.hogFunction(MOCK_HOG_FUNCTION_ID, 'backfills'),
    },
    decorators: [
        mswDecorator({
            ...commonMocks,
            get: {
                ...commonMocks.get,
                [`/api/environments/:team_id/batch_exports/${MOCK_BATCH_EXPORT_ID}/backfills/`]: {
                    results: MOCK_BACKFILLS,
                    next: null,
                },
            },
        }),
    ],
}

export const BackfillsEmpty: Story = {
    parameters: {
        pageUrl: urls.hogFunction(MOCK_HOG_FUNCTION_ID, 'backfills'),
    },
}

export const RunsWithData: Story = {
    parameters: {
        pageUrl: urls.hogFunction(MOCK_HOG_FUNCTION_ID, 'runs'),
    },
    decorators: [
        mswDecorator({
            ...commonMocks,
            get: {
                ...commonMocks.get,
                [`/api/environments/:team_id/batch_exports/${MOCK_BATCH_EXPORT_ID}/backfills/`]: {
                    results: [],
                    next: null,
                },
                [`/api/environments/:team_id/batch_exports/${MOCK_BATCH_EXPORT_ID}/runs/`]: {
                    results: [
                        {
                            id: 'run-001',
                            status: 'Completed',
                            created_at: '2024-01-15T10:00:00Z',
                            data_interval_start: '2024-01-15T09:00:00Z',
                            data_interval_end: '2024-01-15T10:00:00Z',
                            records_completed: 500,
                        },
                        {
                            id: 'run-002',
                            status: 'Failed',
                            created_at: '2024-01-15T09:00:00Z',
                            data_interval_start: '2024-01-15T08:00:00Z',
                            data_interval_end: '2024-01-15T09:00:00Z',
                            records_completed: 0,
                            latest_error: 'HTTP fetch failed on attempt 3 with status code 500.',
                        },
                        {
                            id: 'run-003',
                            status: 'Running',
                            created_at: '2024-01-15T11:00:00Z',
                            data_interval_start: '2024-01-15T10:00:00Z',
                            data_interval_end: '2024-01-15T11:00:00Z',
                        },
                    ],
                    next: null,
                },
            },
        }),
    ],
}

export const RunsEmpty: Story = {
    parameters: {
        pageUrl: urls.hogFunction(MOCK_HOG_FUNCTION_ID, 'runs'),
    },
}

export const Configuration: Story = {
    parameters: {
        pageUrl: urls.hogFunction(MOCK_HOG_FUNCTION_ID),
    },
}

const MOCK_HOG_FUNCTION_LOG_RESULTS = {
    results: [
        [
            'invocation-aaa-bbb-ccc',
            '2024-01-15 10:00:00.000001',
            'DEBUG',
            "Executing function on event 'https://example.com/events/abc123'",
        ],
        ['invocation-aaa-bbb-ccc', '2024-01-15 10:00:00.050002', 'INFO', 'fetch(POST, https://example.com/webhook)'],
        [
            'invocation-aaa-bbb-ccc',
            '2024-01-15 10:00:00.250003',
            'DEBUG',
            "Function completed in 250ms. Sync: 2ms. Mem: 128kb. Ops: 42. Event: 'https://example.com/events/abc123'",
        ],
        [
            'invocation-ddd-eee-fff',
            '2024-01-15 10:01:00.000001',
            'DEBUG',
            "Executing function on event 'https://example.com/events/def456'",
        ],
        ['invocation-ddd-eee-fff', '2024-01-15 10:01:00.050002', 'INFO', 'fetch(POST, https://example.com/webhook)'],
        [
            'invocation-ddd-eee-fff',
            '2024-01-15 10:01:00.350003',
            'ERROR',
            'HTTP fetch failed on attempt 1 with status code 500. Retrying in 1000ms.',
        ],
        [
            'invocation-ddd-eee-fff',
            '2024-01-15 10:01:01.400004',
            'ERROR',
            'HTTP fetch failed on attempt 2 with status code 500. Retrying in 2000ms.',
        ],
        [
            'invocation-ddd-eee-fff',
            '2024-01-15 10:01:03.500005',
            'ERROR',
            'HTTP fetch failed on attempt 3 with status code 500.',
        ],
        [
            'invocation-ggg-hhh-iii',
            '2024-01-15 10:02:00.000001',
            'DEBUG',
            "Executing function on event 'https://example.com/events/ghi789'",
        ],
        ['invocation-ggg-hhh-iii', '2024-01-15 10:02:00.050002', 'INFO', 'fetch(POST, https://example.com/webhook)'],
        [
            'invocation-ggg-hhh-iii',
            '2024-01-15 10:02:00.150003',
            'DEBUG',
            "Function completed in 150ms. Sync: 1ms. Mem: 96kb. Ops: 38. Event: 'https://example.com/events/ghi789'",
        ],
    ],
}

export const Logs: Story = {
    parameters: {
        pageUrl: urls.hogFunction(MOCK_HOG_FUNCTION_ID, 'logs'),
    },
    decorators: [
        mswDecorator({
            ...commonMocks,
            get: {
                ...commonMocks.get,
                [`/api/environments/:team_id/batch_exports/${MOCK_BATCH_EXPORT_ID}/backfills/`]: {
                    results: [],
                    next: null,
                },
            },
            post: {
                ...commonMocks.post,
                '/api/environments/:team_id/query/HogQLQuery/': MOCK_HOG_FUNCTION_LOG_RESULTS,
            },
        }),
    ],
}
