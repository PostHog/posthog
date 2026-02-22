import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

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
