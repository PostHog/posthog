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

function scoutReport(id: string, scoutName: string, createdAt: string, title: string, summary: string): object {
    return {
        id,
        title,
        summary,
        summary_lead: summary,
        scout_name: scoutName,
        created_at: createdAt,
        updated_at: createdAt,
        status: 'ready',
        charts: [],
        source_products: ['signals_scout'],
    }
}

const SCOUT_REPORTS = [
    scoutReport(
        'report-replay',
        'signals-scout-session-replay',
        '2026-09-27T16:00:00Z',
        'People get stuck on the billing form',
        'Nine people clicked a disabled Save button on the billing form more than five times this week.\n\n**Evidence**\n\n- The button waits for a valid postcode.'
    ),
    scoutReport(
        'report-experiment',
        'signals-scout-experiments',
        '2026-09-26T09:00:00Z',
        'Onboarding checklist experiment has a winner',
        'The onboarding checklist experiment reached significance: the test variant activates 12% more new projects than control.'
    ),
    scoutReport(
        'report-ci',
        'signals-scout-ci-health',
        '2026-09-27T10:00:00Z',
        'fix(ci): A billing test is flaky',
        'A billing test failed three times on master this week.'
    ),
]

async function queryHandler({ request }: { request: Request }): Promise<[number, unknown]> {
    const body = (await request.json()) as { query?: { tags?: { name?: string } } }
    switch (body.query?.tags?.name) {
        case 'today_feed_event_counts':
            return [200, { results: eventCounts() }]
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
                '/api/projects/:team_id/signals/reports/': {
                    count: SCOUT_REPORTS.length,
                    next: null,
                    previous: null,
                    results: SCOUT_REPORTS,
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
