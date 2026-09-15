import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const SOURCE_ID = '0196b144-1f82-0000-0d0d-a01de54d6801'

const source = {
    id: SOURCE_ID,
    source_id: 'src_example',
    connection_id: 'conn_example',
    status: 'Completed',
    source_type: 'Stripe',
    prefix: null,
    description: null,
    access_method: 'warehouse',
    created_via: 'web',
    latest_error: null,
    schemas: [],
    sync_frequency: '24hour',
    job_inputs: {},
    revenue_analytics_config: { enabled: false, include_invoiceless_charges: true },
    user_access_level: 'editor',
}

const slackNotification = {
    id: '0196b144-1f82-0000-0d0d-a01de54d6802',
    name: 'Post to Slack on source sync failure',
    type: 'internal_destination',
    enabled: true,
    icon_url: '/static/services/slack.png',
    template: { id: 'template-slack', name: 'Slack', icon_url: '/static/services/slack.png' },
    inputs_schema: [],
    inputs: {},
    filters: {
        source: 'internal-events',
        events: [{ id: '$warehouse_source_sync_failed', type: 'events' }],
        properties: [{ key: 'source_id', type: 'event', value: SOURCE_ID, operator: 'exact' }],
    },
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Warehouse/Source notifications tab',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.dataWarehouseSource(`managed-${SOURCE_ID}`, 'notifications'),
        mockDate: '2026-09-15',
        featureFlags: [FEATURE_FLAGS.WAREHOUSE_SOURCE_SYNC_ALERTS],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/external_data_sources/wizard/': {},
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const NoNotifications: Story = {
    decorators: [
        mswDecorator({
            get: {
                [`/api/environments/:team_id/external_data_sources/${SOURCE_ID}/`]: source,
            },
        }),
    ],
}

export const WithSlackNotification: Story = {
    decorators: [
        mswDecorator({
            get: {
                [`/api/environments/:team_id/external_data_sources/${SOURCE_ID}/`]: source,
                '/api/environments/:team_id/hog_functions/': { count: 1, results: [slackNotification], next: null },
            },
        }),
    ],
}
