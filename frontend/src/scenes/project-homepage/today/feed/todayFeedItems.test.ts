import { dayjs } from 'lib/dayjs'

import type { TeamType } from '~/types'

import { type DayCount, type TodayFeedPost, feedDays, movementPosts, tryPost } from './todayFeedItems'

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

        expect(events(movementPosts(counts, DAYS, { [hidden.key]: true }))).toEqual(['search', 'export', 'upload'])
    })

    it.each<{
        name: string
        team: TeamType
        events: string[]
        hidden: Record<string, true>
        product: string | null
    }>([
        {
            name: 'every product in use',
            team: team(),
            events: ['$pageview', '$feature_flag_called'],
            hidden: {},
            product: null,
        },
        {
            name: 'replay off',
            team: team({ session_recording_opt_in: false }),
            events: ['$pageview', '$feature_flag_called'],
            hidden: {},
            product: 'session_replay',
        },
        {
            name: 'replay off but hidden',
            team: team({ session_recording_opt_in: false }),
            events: ['$pageview', '$feature_flag_called'],
            hidden: { 'try:session_replay': true },
            product: null,
        },
        {
            name: 'errors captured without the setting',
            team: team({ autocapture_exceptions_opt_in: false }),
            events: ['$pageview', '$feature_flag_called', '$exception'],
            hidden: {},
            product: null,
        },
        {
            name: 'heatmaps off without web traffic',
            team: team({ heatmaps_opt_in: false }),
            events: ['$screen', '$feature_flag_called'],
            hidden: {},
            product: null,
        },
    ])('picks the product to try when $name', ({ team, events, hidden, product }) => {
        const counts = events.map((name) => ({ name, daysAgo: 1, count: 1 }))

        expect(tryPost(team, counts, hidden, 0)?.product ?? null).toBe(product)
    })
})
