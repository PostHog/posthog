import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

function eventCounts(): [string, number, number][] {
    const rows: [string, number, number][] = []
    for (let daysAgo = 1; daysAgo <= 14; daysAgo++) {
        const thisWeek = daysAgo <= 7
        rows.push(['$pageview', daysAgo, 5000 + (daysAgo % 3) * 120])
        rows.push(['checkout_completed', daysAgo, thisWeek ? 640 + daysAgo * 12 : 400 + daysAgo * 4])
        rows.push(['signup_started', daysAgo, thisWeek ? 140 + daysAgo * 3 : 310])
        if (thisWeek) {
            rows.push(['invite_sent', daysAgo, 90 - daysAgo * 6])
        }
    }
    return rows
}

function pageCounts(): [string, number, number][] {
    const rows: [string, number, number][] = []
    for (let daysAgo = 1; daysAgo <= 14; daysAgo++) {
        const thisWeek = daysAgo <= 7
        rows.push(['/pricing', daysAgo, thisWeek ? 900 + daysAgo * 20 : 520])
        rows.push(['/docs', daysAgo, 2000 + (daysAgo % 2) * 50])
    }
    return rows
}

async function queryHandler({ request }: { request: Request }): Promise<[number, unknown]> {
    const body = (await request.json()) as { query?: { tags?: { name?: string } } }
    switch (body.query?.tags?.name) {
        case 'today_feed_event_counts':
            return [200, { results: eventCounts() }]
        case 'today_feed_page_counts':
            return [200, { results: pageCounts() }]
        case 'today_feed_rage_session':
            return [
                200,
                { results: [['session-rage-1', 14, 'https://example.com/checkout/payment', '2026-09-27T14:05:00Z']] },
            ]
        default:
            return [200, { results: [] }]
    }
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Project Homepage/Today feed',
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/file_system/': { results: [], count: 0 },
                '/api/environments/:team_id/file_system/unfiled/': { results: [], count: 0 },
                '/api/projects/:team_id/file_system/frequent/': [],
                '/api/projects/:team_id/vision/scanners/highlight_feed/': {
                    results: [],
                    has_more: false,
                    as_of: '2026-09-28T18:30:00Z',
                },
                '/api/projects/:team_id/insights/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [
                        {
                            id: 501,
                            short_id: 'feed0001',
                            name: 'Weekly signups by plan',
                            derived_name: null,
                            description: 'Signups each week, split by the plan people pick.',
                            created_at: '2026-09-26T10:12:00Z',
                            created_by: {
                                id: 7,
                                uuid: 'user-grace',
                                distinct_id: 'user-grace',
                                first_name: 'Grace',
                                last_name: 'Hopper',
                                email: 'grace@example.com',
                            },
                        },
                    ],
                },
                'https://us.i.posthog.com/api/early_access_features': {
                    earlyAccessFeatures: [
                        {
                            name: 'Funnel step notes',
                            description: 'Write a note on any funnel step for your team to read.',
                            stage: 'beta',
                            flagKey: 'funnel-step-notes',
                            documentationUrl: '',
                        },
                    ],
                },
            },
            post: {
                '/api/environments/:team_id/query/:kind/': queryHandler,
                '/api/projects/:team_id/file_system/home_folder/': { id: null, path: null },
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-28 18:30:00',
        pageUrl: urls.todayFeed(),
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.TODAY_FEED],
        testOptions: { snapshotBrowsers: [], waitForLoadersToDisappear: true },
    },
}
export default meta

type Story = StoryObj<{}>

export const Feed: Story = {}
