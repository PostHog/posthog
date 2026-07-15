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

// One row of the tool-signals HogQL aggregate: total, prod, custom, exceptions,
// backend, flag calls, pageviews, survey responses, AI generations
const TOOL_SIGNALS_ROW = [54210, 32480, 1800, 42, 5400, 1200, 27904, 12, 0]

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
