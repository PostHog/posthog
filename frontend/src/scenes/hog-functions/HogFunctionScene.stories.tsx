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
    name: 'Export to S3',
    description: 'Export events to an S3 bucket',
    enabled: true,
    deleted: false,
    hog: '',
    bytecode: [],
    inputs_schema: [],
    inputs: {},
    filters: {},
    icon_url: null,
    template: null,
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
    name: 'S3 Export',
    destination: {
        type: 'S3',
        config: {
            bucket_name: 'my-bucket',
            region: 'us-east-1',
            prefix: 'posthog/',
        },
    },
    interval: 'hour',
    paused: false,
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
        // hogFunctionBackfillsLogic calls enableBackfills on mount before the config has loaded,
        // so this endpoint must be mocked even though the hog function already has a batch_export_id
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

type Story = StoryObj<typeof meta>

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

export const Configuration: Story = {
    parameters: {
        pageUrl: urls.hogFunction(MOCK_HOG_FUNCTION_ID),
    },
}
