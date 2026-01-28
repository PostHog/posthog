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
    url: `${window.location.origin}/mock-heatmap-page.html`,
    data_url: `${window.location.origin}/mock-heatmap-page.html`,
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
            // 1800 = ceil((maxY + 100) / 100) * 100 where maxY=1700 from mock data below
            waitForSelector: '.heatmaps-ready[data-height-override="1800"] canvas.heatmap-canvas',
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
                                { pointer_relative_x: 0.5, pointer_target_fixed: false, pointer_y: 150, count: 25 },
                                { pointer_relative_x: 0.4, pointer_target_fixed: false, pointer_y: 300, count: 20 },
                                { pointer_relative_x: 0.52, pointer_target_fixed: false, pointer_y: 500, count: 12 },
                                { pointer_relative_x: 0.3, pointer_target_fixed: false, pointer_y: 800, count: 8 },
                                { pointer_relative_x: 0.25, pointer_target_fixed: false, pointer_y: 1100, count: 5 },
                                { pointer_relative_x: 0.6, pointer_target_fixed: false, pointer_y: 1400, count: 10 },
                                { pointer_relative_x: 0.45, pointer_target_fixed: false, pointer_y: 1700, count: 6 },
                            ],
                            count: 7,
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
