import { dayjs } from 'lib/dayjs'

import type { TeamType } from '~/types'

import { type EventDayCount, feedDays, movementItems, tryItem } from './todayFeedItems'

const DAYS = feedDays(dayjs('2026-03-15'))

function week(event: string, previous: number, current: number): EventDayCount[] {
    return [
        { event, daysAgo: 10, count: previous },
        { event, daysAgo: 3, count: current },
    ]
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

        const items = movementItems(counts, DAYS, {})

        expect(items.map((item) => item.title)).toEqual([
            'checkout is down 80% this week',
            'signup_started is up 200% this week',
        ])
        expect(items[0].series).toHaveLength(DAYS.length)
    })

    it('shows a new event next to a change', () => {
        const counts = [...week('invite_sent', 0, 900), ...week('checkout', 2000, 400)]

        expect(movementItems(counts, DAYS, {}).map((item) => item.title)).toEqual([
            'invite_sent started this week, with 900 events so far',
            'checkout is down 80% this week',
        ])
    })

    it('fills the place of a hidden change with the next one', () => {
        const counts = [...week('checkout', 2000, 400), ...week('search', 1000, 300), ...week('upload', 1000, 2000)]
        const [hidden] = movementItems(counts, DAYS, {})

        const items = movementItems(counts, DAYS, { [hidden.key]: true })

        expect(items.map((item) => item.key)).not.toContain(hidden.key)
        expect(items).toHaveLength(2)
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
        const counts = events.map((event) => ({ event, daysAgo: 1, count: 1 }))

        expect(tryItem(team, counts, hidden, 0)?.product ?? null).toBe(product)
    })
})
