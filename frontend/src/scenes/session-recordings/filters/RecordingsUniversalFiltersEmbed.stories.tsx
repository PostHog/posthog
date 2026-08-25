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
                '/api/environments/:team_id/session_recordings': ({ request }) => {
                    const version = new URL(request.url).searchParams.get('version')
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

const withPageFilter = (values: Record<string, any>[]): Record<string, any> => ({
    pageUrl: combineUrl(urls.replay(), {
        showFilters: true,
        filters: {
            date_from: '-3d',
            date_to: null,
            filter_test_accounts: false,
            duration: [{ type: 'recording', key: 'duration', value: 1, operator: 'gt' }],
            filter_group: { type: 'AND', values: [{ type: 'AND', values }] },
        },
    }).url,
})

export const PageFilterWithSwapOffered: Story = {
    parameters: withPageFilter([{ type: 'event', key: '$current_url', operator: 'icontains', value: '/pricing' }]),
}

export const PageviewFilterWithSwapOffered: Story = {
    parameters: withPageFilter([
        {
            id: '$pageview',
            name: '$pageview',
            type: 'events',
            properties: [{ type: 'event', key: '$current_url', operator: 'icontains', value: '/pricing' }],
        },
    ]),
}

// An exact pathname cannot be rewritten: recorded URLs are absolute, so the value would stop matching.
export const PageFilterThatCannotBeSwapped: Story = {
    parameters: withPageFilter([{ type: 'event', key: '$pathname', operator: 'exact', value: '/pricing' }]),
}
