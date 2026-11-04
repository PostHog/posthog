import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import externalDataSourceResponseMock from '~/mocks/fixtures/api/projects/team_id/external_data_sources/externalDataSource.json'

import type { ExternalDataDestinationApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import { FailingDestinationsBanner } from './FailingDestinationsBanner'

const FAILING: ExternalDataDestinationApi = {
    id: 'failing-postgres',
    type: 'Postgres',
    name: 'Analytics Postgres',
    is_posthog_warehouse: false,
    status: 'failing',
    latest_error: 'Analytics Postgres: Could not connect to the database.',
    latest_error_at: '2026-08-20T10:00:00Z',
    created_at: '2026-08-20T10:00:00Z',
    updated_at: null,
    created_by: null,
    synced_sources: [],
}
const PAUSED: ExternalDataDestinationApi = {
    ...FAILING,
    id: 'paused-postgres',
    name: 'Reporting Postgres',
    status: 'paused',
    latest_error: 'Reporting Postgres: Destination configuration error. The database does not exist.',
}

type BannerStoryProps = { sourceId: string; destinations: ExternalDataDestinationApi[] }
type Story = StoryObj<BannerStoryProps>
const meta: Meta<BannerStoryProps> = {
    title: 'Scenes-App/Data Warehouse/Settings/Failing destinations',
    component: FailingDestinationsBanner,
    args: { sourceId: '123' },
    parameters: { mockDate: '2026-08-20', viewMode: 'story' },
    render: ({ sourceId, destinations }) => {
        useStorybookMocks({
            get: {
                '/api/environments/:team_id/external_data_destinations': () => [
                    200,
                    { results: destinations, count: destinations.length, next: null, previous: null },
                ],
                '/api/environments/:team_id/external_data_sources/:id/destinations': () => [
                    200,
                    { destination_ids: destinations.map((destination) => destination.id) },
                ],
                '/api/environments/:team_id/external_data_sources/:id': () => [
                    200,
                    { ...externalDataSourceResponseMock, id: sourceId, schemas: [] },
                ],
            },
        })

        return <FailingDestinationsBanner sourceId={sourceId} />
    },
}
export default meta

export const Failing: Story = { args: { destinations: [FAILING] } }
export const Paused: Story = { args: { destinations: [PAUSED] } }
export const FailingAndPaused: Story = { args: { destinations: [FAILING, PAUSED] } }
