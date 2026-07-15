import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'

// Deterministic stand-in for the posthog.com blog feed the publications rail streams
const BLOG_RSS = `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
    <channel>
        <title>PostHog blog</title>
        <item>
            <title>How we built the quickstart page</title>
            <link>https://posthog.com/blog/quickstart-page</link>
            <description>Every tool on one screen, powered by the same events.</description>
            <pubDate>Mon, 13 Jul 2026 10:00:00 GMT</pubDate>
            <dc:creator>Max Hedgehog</dc:creator>
        </item>
        <item>
            <title>Session replay, now with hogs</title>
            <link>https://posthog.com/blog/replay-hogs</link>
            <description>Watch real users navigate your app, narrated by hedgehogs.</description>
            <pubDate>Thu, 09 Jul 2026 10:00:00 GMT</pubDate>
            <dc:creator>Max Hedgehog</dc:creator>
        </item>
        <item>
            <title>Feature flags without the foot-guns</title>
            <link>https://posthog.com/blog/safe-flags</link>
            <description>Roll out changes to the right users, safely.</description>
            <pubDate>Wed, 01 Jul 2026 10:00:00 GMT</pubDate>
            <dc:creator>Max Hedgehog</dc:creator>
        </item>
    </channel>
</rss>`

// One row of the tool-signals HogQL aggregate: total, prod, custom, distinct custom,
// identify, exceptions, server exceptions, backend, flag calls, prod flag calls, pageviews,
// prod pageviews, survey responses, AI generations, AI trace events, MCP init, MCP tool calls.
// The replay-count query shares this mock, so its count reads the first column.
const TOOL_SIGNALS_ROW = [54210, 32480, 1800, 8, 900, 42, 3, 5400, 1200, 800, 27904, 21000, 12, 0, 0, 0, 0]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Quickstart',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-07-15',
        pageUrl: urls.quickstart(),
        // The scene only renders for the test variant of the experiment flag
        featureFlags: { [FEATURE_FLAGS.QUICKSTART_HOMEPAGE]: 'test' },
    },
    // External artwork (Cloudinary hero, Substack covers) makes pixel snapshots nondeterministic
    tags: ['test-skip'],
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: true,
                    realm: 'cloud',
                },
                '/api/billing/': billingJson,
                // liveEventsHostOrigin() points at the Storybook origin, so the live users chip gets a count
                '/stats': { users_on_product: 342 },
                '/api/environments/:team_id/logs/has_logs': { hasLogs: false },
                '/api/environments/:team_id/external_data_sources/': { results: [{ id: '1' }, { id: '2' }] },
                '/api/environments/:team_id/hog_flows/': {
                    results: [{ id: '1', status: 'active', trigger: { type: 'event' } }],
                },
                '/api/environments/:team_id/error_tracking/symbol_sets/': { count: 1, results: [] },
                '/api/environments/:team_id/hog_functions/': { count: 0, results: [] },
                '/api/projects/:team_id/conversations/tickets/': { count: 12, results: [] },
                'https://posthog.com/rss.xml': () =>
                    new Response(BLOG_RSS, { status: 200, headers: { 'Content-Type': 'application/rss+xml' } }),
            },
            post: {
                '/api/environments/:team_id/query': { results: [TOOL_SIGNALS_ROW] },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const Base: Story = {}
