import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { RawBatchExportBackfill } from '~/types'

import batchExports from '../__mocks__/batchExports.json'

const EXISTING_EXPORT = {
    ...batchExports.results[0],
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
    {
        id: 'backfill-004',
        status: 'Starting',
        created_at: '2024-01-15T11:00:00Z',
        start_at: '2024-01-14T00:00:00Z',
        end_at: '2024-01-15T00:00:00Z',
        last_updated_at: '2024-01-15T11:00:00Z',
    },
]

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

type Story = StoryObj<typeof meta>

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
