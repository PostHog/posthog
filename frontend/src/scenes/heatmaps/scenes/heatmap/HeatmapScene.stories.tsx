import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const generatingSaved = {
    id: 100,
    short_id: 'hm_gen',
    name: 'Generating…',
    url: 'https://posthog.github.io/placeholder',
    data_url: 'https://posthog.github.io/placeholder',
    target_widths: [768, 1024],
    type: 'screenshot',
    status: 'processing',
    has_content: false,
    snapshots: [],
    deleted: false,
    created_by: { id: 1, uuid: 'user-1', distinct_id: 'd1', first_name: 'Alice', email: 'alice@ph.com' },
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    exception: null,
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Heatmap',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.heatmap('hm_gen'),
        testOptions: {
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/saved/hm_gen/': generatingSaved,
                '/api/environments/:team_id/heatmap_screenshots/:id/content/': (_req, res, ctx) =>
                    res(ctx.status(202), ctx.json(generatingSaved)),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const Generating: Story = {
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
        },
    },
}

const iframeSaved = {
    id: 101,
    short_id: 'hm_iframe',
    name: 'Iframe placeholder',
    url: 'https://posthog.github.io/placeholder',
    data_url: 'https://posthog.github.io/placeholder',
    target_widths: [],
    type: 'iframe',
    status: 'completed',
    has_content: false,
    snapshots: [],
    deleted: false,
    created_by: { id: 1, uuid: 'user-1', distinct_id: 'd1', first_name: 'Alice', email: 'alice@ph.com' },
    created_at: '2024-01-03T00:00:00Z',
    updated_at: '2024-01-03T00:00:00Z',
    exception: null,
}

export const IframeExample: Story = {
    parameters: {
        pageUrl: urls.heatmap('hm_iframe'),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/saved/hm_iframe/': iframeSaved,
            },
        }),
    ],
}

export const New: Story = {
    parameters: {
        pageUrl: urls.heatmap('new'),
    },
}
