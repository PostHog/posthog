import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const generatingSaved = {
    id: 100,
    short_id: 'hm_gen',
    name: 'Generating…',
    url: 'https://example.com',
    data_url: 'https://example.com',
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

const makeIframeSaved = (): Record<string, unknown> => ({
    id: 101,
    short_id: 'hm_iframe',
    name: 'Iframe example.com',
    url: `${window.location.origin}/mock-page.html`,
    data_url: `${window.location.origin}/mock-page.html`,
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
})

export const IframeExample: Story = {
    parameters: {
        pageUrl: urls.heatmap('hm_iframe'),
        testOptions: {
            // Wait for heatmap canvas to be ready with data loaded
            waitForSelector: '.heatmaps-ready',
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/saved/hm_iframe/': (_req, res, ctx) =>
                    res(ctx.status(200), ctx.json(makeIframeSaved())),
                '/api/heatmap/': (_req, res, ctx) =>
                    res(
                        ctx.status(200),
                        ctx.json({
                            results: [
                                { pointer_relative_x: 0.4, pointer_target_fixed: false, pointer_y: 355, count: 85 },
                                { pointer_relative_x: 0.7, pointer_target_fixed: false, pointer_y: 24, count: 32 },
                                { pointer_relative_x: 0.77, pointer_target_fixed: false, pointer_y: 24, count: 28 },
                                { pointer_relative_x: 0.84, pointer_target_fixed: false, pointer_y: 24, count: 15 },
                                { pointer_relative_x: 0.91, pointer_target_fixed: false, pointer_y: 24, count: 12 },
                                { pointer_relative_x: 0.1, pointer_target_fixed: false, pointer_y: 24, count: 18 },
                                { pointer_relative_x: 0.17, pointer_target_fixed: false, pointer_y: 395, count: 22 },
                                { pointer_relative_x: 0.5, pointer_target_fixed: false, pointer_y: 395, count: 19 },
                                { pointer_relative_x: 0.83, pointer_target_fixed: false, pointer_y: 395, count: 14 },
                            ],
                            count: 9,
                            next: null,
                            previous: null,
                        })
                    ),
            },
        }),
    ],
}

export const New: Story = {
    parameters: {
        pageUrl: urls.heatmap('new'),
    },
}
