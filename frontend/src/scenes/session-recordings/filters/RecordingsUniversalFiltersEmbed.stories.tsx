import { Meta, StoryObj } from '@storybook/react'
import { combineUrl } from 'kea-router'

import { App } from 'scenes/App'
import recordingEventsJson from 'scenes/session-recordings/__mocks__/recording_events_query'
import { recordingPlaylists } from 'scenes/session-recordings/__mocks__/recording_playlists'
import { recordings } from 'scenes/session-recordings/__mocks__/recordings'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'

const billingJsonWithProductAnalyticsOverLimit = {
    ...billingJson,
    products: billingJson.products.map((product) =>
        product.type === 'product_analytics' ? { ...product, percentage_usage: 1.5 } : product
    ),
}

const meta: Meta = {
    component: App,
    title: 'Replay/Tabs/Home/Filters Banner',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-01',
        pageUrl: combineUrl(urls.replay(), { showFilters: true }).url,
    },
    decorators: [
        mswDecorator({
            get: {
                '/stats': () => [200, { users_on_product: 42, active_recordings: 7 }],
                '/api/projects/:team_id/session_recording_playlists': recordingPlaylists,
                '/api/environments/:team_id/session_recordings': (req) => {
                    const version = req.url.searchParams.get('version')
                    return [200, { has_next: false, results: recordings, version }]
                },
            },
            post: {
                '/api/environments/:team_id/query/:kind': recordingEventsJson,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const ProductAnalyticsOverLimit: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/billing/': () => [200, billingJsonWithProductAnalyticsOverLimit],
            },
        }),
    ],
}

export const ProductAnalyticsUnderLimit: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/billing/': () => [200, billingJson],
            },
        }),
    ],
}
