import { dayjs } from 'lib/dayjs'

import type { TeamType } from '~/types'

import {
    type DayCount,
    type FeedScoutReport,
    type TodayFeedPost,
    FEED_TEXT_LIMIT,
    featurePosts,
    feedDays,
    movementPosts,
    scoutPosts,
} from './todayFeedItems'

const DAYS = feedDays(dayjs('2026-03-15'))

function week(name: string, previous: number, current: number): DayCount[] {
    return [
        { name, daysAgo: 10, count: previous },
        { name, daysAgo: 3, count: current },
    ]
}

function events(posts: TodayFeedPost[]): string[] {
    return posts.map((post) => (post.media?.type === 'chart' ? post.media.label : post.key))
}

function team(overrides: Partial<TeamType> = {}): TeamType {
    return {
        session_recording_opt_in: true,
        heatmaps_opt_in: true,
        autocapture_exceptions_opt_in: true,
        surveys_opt_in: true,
        ...overrides,
    } as TeamType
}

describe('todayFeedItems', () => {
    it('picks the biggest real changes and tells paired events once', () => {
        const counts = [
            ...week('signup_started', 1000, 3000),
            ...week('signup_finished', 500, 1500),
            ...week('checkout', 2000, 400),
            ...week('$feature_flag_called', 100, 90000),
            ...week('rare_event', 10, 150),
            ...week('steady_event', 5000, 5200),
        ]

        const posts = movementPosts(counts, DAYS, {})

        expect(events(posts)).toEqual(['checkout', 'signup_started'])
        expect(posts[0].text).toBe('checkout is down 80% this week. 400 events, against 2K the week before.')
    })

    it('shows a new event next to a change', () => {
        const counts = [...week('invite_sent', 0, 900), ...week('checkout', 2000, 400)]

        expect(events(movementPosts(counts, DAYS, {}))).toEqual(['invite_sent', 'checkout'])
    })

    it('fills the place of a hidden change with the next one', () => {
        const counts = [
            ...week('checkout', 2000, 400),
            ...week('search', 1000, 300),
            ...week('export', 1000, 2600),
            ...week('upload', 1000, 2000),
        ]
        const [hidden] = movementPosts(counts, DAYS, {})

        expect(events(movementPosts(counts, DAYS, { [hidden.key]: true }))).toEqual(['search', 'export'])
    })

    it('posts only data scout findings, as one short sentence with the insight they cite', () => {
        const report = (overrides: Partial<FeedScoutReport>): FeedScoutReport => ({
            id: 'report-1',
            title: 'Signups dropped',
            summary: '',
            summary_lead: '',
            scout_name: 'signals-scout-anomaly-detection',
            created_at: '2026-03-14T09:00:00Z',
            charts: [],
            ...overrides,
        })
        const longSentence = `Weekly signups on the pricing page fell to 120 on March 13, ${'well below the usual range '.repeat(8)}.`

        const posts = scoutPosts(
            [
                report({ id: 'ci', scout_name: 'signals-scout-ci-health', summary: 'A test is flaky.' }),
                report({
                    id: 'anomaly',
                    summary: `${longSentence} See [the signups insight](https://app.example.com/project/1/insights/AbCd1234).\n\n**Evidence**`,
                }),
                report({
                    id: 'flags',
                    scout_name: 'signals-scout-feature-flags',
                    title: 'fix(flags): Remove a stale flag',
                }),
            ],
            {}
        )

        expect(posts.map((post) => post.key)).toEqual(['scout:anomaly', 'scout:flags'])
        expect(posts[0].text.length).toBeLessThanOrEqual(FEED_TEXT_LIMIT)
        expect(posts[0].text.endsWith('…')).toBe(true)
        expect(posts[0].media).toMatchObject({ type: 'report-chart', chart: { query: { shortId: 'AbCd1234' } } })
        expect(posts[1].text).toBe('Remove a stale flag')
    })

    it.each<{
        name: string
        team: TeamType
        extraEvents: string[]
        hasScoutPosts: boolean
        hidden: Record<string, true>
        products: string[]
    }>([
        {
            name: 'every detectable product in use',
            team: team(),
            extraEvents: [],
            hasScoutPosts: true,
            hidden: {},
            products: ['experiments', 'logs'],
        },
        {
            name: 'replay off',
            team: team({ session_recording_opt_in: false }),
            extraEvents: [],
            hasScoutPosts: true,
            hidden: {},
            products: ['experiments', 'session_replay'],
        },
        {
            name: 'replay off but hidden',
            team: team({ session_recording_opt_in: false }),
            extraEvents: [],
            hasScoutPosts: true,
            hidden: { 'feature:session_replay': true },
            products: ['experiments', 'logs'],
        },
        {
            name: 'errors captured without the setting',
            team: team({ autocapture_exceptions_opt_in: false }),
            extraEvents: ['$exception'],
            hasScoutPosts: true,
            hidden: {},
            products: ['experiments', 'logs'],
        },
        {
            name: 'no scout posts yet',
            team: team(),
            extraEvents: [],
            hasScoutPosts: false,
            hidden: {},
            products: ['scouts', 'experiments'],
        },
    ])('suggests $products when $name', ({ team, extraEvents, hasScoutPosts, hidden, products }) => {
        const counts = ['$pageview', '$feature_flag_called', '$ai_generation', ...extraEvents].map((name) => ({
            name,
            daysAgo: 1,
            count: 1,
        }))

        expect(featurePosts(team, counts, hasScoutPosts, hidden, 0).map((post) => post.product)).toEqual(products)
    })
})
