import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const STORAGE_KEY = 'ph_replay_fixed_heatmap_storybook'

const snapshotHtml = `<!DOCTYPE html><html><head><style>
* { margin: 0; box-sizing: border-box; font-family: Arial, Helvetica, sans-serif; }
body { width: 1024px; background: #fff; }
header { display: flex; gap: 24px; padding: 18px 32px; background: #1d1f27; }
header a { color: #f7f7f7; font-size: 14px; text-decoration: none; }
main { padding: 48px 32px; }
h1 { font-size: 28px; margin-bottom: 12px; color: #111; }
p { color: #4b4b52; margin-bottom: 28px; max-width: 480px; font-size: 15px; }
#signup-cta { background: #f54e00; color: #fff; border: none; padding: 14px 28px; font-size: 16px; border-radius: 6px; }
#docs-link { display: inline-block; margin-left: 20px; color: #f54e00; font-size: 16px; }
</style></head><body>
<header><a id="nav-home" href="/">Home</a><a id="nav-pricing" href="/pricing">Pricing</a><a id="nav-docs" href="/docs">Docs</a></header>
<main><h1>Simple, usage-based pricing</h1>
<p>Pay only for what you use. Every product has a generous free tier, and you can set billing limits so there are no surprises.</p>
<button id="signup-cta">Get started - free</button>
<a id="docs-link" href="/docs">Read the docs</a></main>
</body></html>`

const replayIframeData = {
    html: snapshotHtml,
    width: 1024,
    height: 640,
    startDateTime: '2024-01-01T00:00:00Z',
    url: 'https://example.com/pricing',
}

const elementStatsResults = [
    {
        count: 128,
        hash: 'story-cta',
        type: '$autocapture',
        elements: [
            {
                text: 'Get started - free',
                tag_name: 'button',
                attr_id: 'signup-cta',
                nth_child: 3,
                nth_of_type: 1,
                attributes: {},
            },
            { tag_name: 'main', nth_child: 2, nth_of_type: 1, attributes: {} },
        ],
    },
    {
        count: 46,
        hash: 'story-docs',
        type: '$autocapture',
        elements: [
            {
                text: 'Read the docs',
                tag_name: 'a',
                attr_id: 'docs-link',
                href: '/docs',
                nth_child: 4,
                nth_of_type: 1,
                attributes: {},
            },
            { tag_name: 'main', nth_child: 2, nth_of_type: 1, attributes: {} },
        ],
    },
    {
        count: 19,
        hash: 'story-nav',
        type: '$autocapture',
        elements: [
            {
                text: 'Pricing',
                tag_name: 'a',
                attr_id: 'nav-pricing',
                href: '/pricing',
                nth_child: 2,
                nth_of_type: 2,
                attributes: {},
            },
            { tag_name: 'header', nth_child: 1, nth_of_type: 1, attributes: {} },
        ],
    },
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Heatmap Recording',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.heatmapRecording(`iframeStorage=${STORAGE_KEY}`),
        featureFlags: [FEATURE_FLAGS.HEATMAPS_RECORDING_CLICKMAP],
        testOptions: {
            waitForSelector: '[data-attr="heatmap-clickmap-overlay"]',
            waitForLoadersToDisappear: true,
        },
    },
    decorators: [
        (Story) => {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(replayIframeData))
            return <Story />
        },
        mswDecorator({
            get: {
                '/api/projects/:team_id/elements/stats/': () => [200, { results: elementStatsResults, next: null }],
                '/api/projects/:team_id/heatmaps/': () => [
                    200,
                    {
                        results: [
                            { pointer_relative_x: 0.12, pointer_target_fixed: false, pointer_y: 210, count: 90 },
                            { pointer_relative_x: 0.14, pointer_target_fixed: false, pointer_y: 214, count: 42 },
                            { pointer_relative_x: 0.3, pointer_target_fixed: false, pointer_y: 212, count: 24 },
                            { pointer_relative_x: 0.1, pointer_target_fixed: false, pointer_y: 28, count: 16 },
                            { pointer_relative_x: 0.18, pointer_target_fixed: false, pointer_y: 28, count: 11 },
                        ],
                        count: 5,
                        next: null,
                        previous: null,
                    },
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const RecordingModeWithClickmap: Story = {}
