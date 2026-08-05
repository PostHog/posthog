import { Meta, StoryObj, type Decorator } from '@storybook/react'
import { delay, HttpResponse } from 'msw'

import { App } from 'scenes/App'
import { heatmapsBrowserLogic } from 'scenes/heatmaps/components/heatmapsBrowserLogic'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

// heatmapsBrowserLogic is unkeyed and singleton, so building it here (before the scene renders)
// seeds loadBannerTimeoutMs on the shared props object. The scene's own build later only
// supplies iframeRef, which merges in rather than replacing what's already there.
const withLoadBannerTimeout =
    (timeoutMs: number): Decorator =>
    (Story) => {
        heatmapsBrowserLogic({ iframeRef: { current: null }, loadBannerTimeoutMs: timeoutMs })
        return <Story />
    }

// Large enough that the load-failure banner's timer can never race the snapshot capture.
const NEVER_BANNER_TIMEOUT_MS = 10 * 60 * 1000

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
                '/api/projects/:team_id/saved/hm_gen/': generatingSaved,
                '/api/projects/:team_id/heatmap_screenshots/:id/content/': () => [202, generatingSaved],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

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
        withLoadBannerTimeout(NEVER_BANNER_TIMEOUT_MS),
        mswDecorator({
            get: {
                '/api/projects/:team_id/saved/hm_iframe/': () => [200, makeIframeSaved()],
                '/api/projects/:team_id/heatmaps/': () => [
                    200,
                    {
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
                    },
                ],
            },
        }),
    ],
}

const makeIframeLoadFailedSaved = (): Record<string, unknown> => ({
    ...makeIframeSaved(),
    id: 102,
    short_id: 'hm_iframe_fail',
    name: 'Iframe load failed',
    url: `${window.location.origin}/mock-page-hangs.html`,
    data_url: `${window.location.origin}/mock-page-hangs.html`,
})

export const IframeLoadFailed: Story = {
    parameters: {
        pageUrl: urls.heatmap('hm_iframe_fail'),
        testOptions: {
            waitForSelector: '.LemonBanner--error',
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        withLoadBannerTimeout(0),
        mswDecorator({
            get: {
                '/api/projects/:team_id/saved/hm_iframe_fail/': () => [200, makeIframeLoadFailedSaved()],
                '/api/projects/:team_id/heatmaps/': () => [200, { results: [], count: 0, next: null, previous: null }],
                // Never resolves, so the iframe's onload never fires and can't race the timer
                // into clearing the banner it just set.
                '/mock-page-hangs.html': async () => {
                    await delay('infinite')
                    return new HttpResponse(null, { status: 200 })
                },
            },
        }),
    ],
}

export const New: Story = {
    parameters: {
        pageUrl: urls.heatmap('new'),
    },
}
