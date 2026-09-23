import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import batchExports from './__mocks__/batchExports.json'
import hogFunctionDestinations from './__mocks__/hogFunctionDestinations.json'

const notification = (id: string, name: string, eventId: string, enabled: boolean): Record<string, unknown> => ({
    id,
    name,
    type: 'internal_destination',
    enabled,
    filters: { source: 'internal-events', events: [{ id: eventId, type: 'events' }] },
    icon_url: '/static/services/slack.png',
    created_by: hogFunctionDestinations.results[0].created_by,
    created_at: '2023-11-02T09:15:00Z',
    updated_at: '2023-12-20T16:40:00Z',
})

const NOTIFICATIONS = {
    count: 3,
    next: null,
    previous: null,
    results: [
        notification('0195f0e8-0000-0000-0000-000000000001', 'Signup alert to #growth', '$insight_alert_firing', true),
        notification(
            '0195f0e8-0000-0000-0000-000000000002',
            'New issues to #on-call',
            '$error_tracking_issue_created',
            true
        ),
        notification(
            '0195f0e8-0000-0000-0000-000000000003',
            'Significant experiment results',
            '$experiment_metric_significant',
            false
        ),
    ],
}

const EMPTY_PAGE = { count: 0, next: null, previous: null, results: [] }

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data pipelines/Destinations',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-01-15',
    },
    decorators: [
        mswDecorator({
            get: {
                // Each tab asks for its own hog function types, so the mock answers by type.
                '/api/environments/:team_id/hog_functions/': ({ request }) =>
                    new URL(request.url).searchParams.get('type') === 'internal_destination'
                        ? NOTIFICATIONS
                        : hogFunctionDestinations,
                '/api/projects/:team_id/hog_functions/masked_secrets/': [],
                '/api/projects/:team_id/batch_exports/': batchExports,
                '/api/environments/:team_id/batch_exports/': batchExports,
                '/api/projects/:team_id/pipeline_destination_configs/': EMPTY_PAGE,
                '/api/organizations/:organization_id/pipeline_destinations/': EMPTY_PAGE,
                '/api/environments/:team_id/external_data_sources/wizard': {},
                '/api/projects/:team_id/activity_log/': { results: [], total_count: 0 },
            },
            post: {
                '/api/environments/:team_id/query/:query_kind/': { results: [] },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Realtime: Story = {
    parameters: { pageUrl: urls.destinations() },
}

export const BatchExports: Story = {
    parameters: { pageUrl: urls.destinations('batch') },
}

export const Notifications: Story = {
    parameters: { pageUrl: urls.destinations('notifications') },
}

export const History: Story = {
    parameters: { pageUrl: urls.destinations('history') },
}
