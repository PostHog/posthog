import type { SignalViewApi } from 'products/today/frontend/generated/api.schemas'

import { dailyTrend, impactNumbers, lastOccurrence } from './todayImpact'
import { signal } from './todayTestFixtures'

function ticket(ticketNumber: number, timestamp: string): SignalViewApi {
    return signal({
        source_product: 'conversations',
        source_id: `ticket-${ticketNumber}`,
        timestamp,
        extra: { ticket_number: ticketNumber },
    })
}

describe('todayImpact', () => {
    test.each([
        [
            'starts at the first day with a value',
            { series: [0, 0, 3, 5], value_at: '2026-10-01T12:00:00Z', query: { source: { interval: 'day' } } },
            { data: [3, 5], since: '30 Sep', start: '2026-09-30' },
        ],
        [
            'keeps the whole window when it is not daily',
            { series: [0, 2, 3], value_at: '2026-10-01T12:00:00Z', query: { source: { interval: 'week' } } },
            { data: [0, 2, 3], since: null, start: null },
        ],
    ])('builds a daily trend that %s', (_, metric, expected) => {
        expect(dailyTrend(metric as never)).toEqual(expected)
    })

    test.each([
        [
            'count distinct support tickets over the days they span',
            [ticket(1042, '2026-09-20T09:00:00Z'), ticket(1043, '2026-09-25T15:00:00Z')],
            [['2', 'support tickets over 6 days.']],
        ],
        [
            'show nothing for one ticket, however many signals cite it',
            [ticket(1042, '2026-09-20T09:00:00Z'), ticket(1042, '2026-09-25T15:00:00Z')],
            [],
        ],
        [
            'work out the database time a slow query costs each day',
            [
                signal({
                    source_product: 'pganalyze',
                    source_type: 'issue',
                    content: '[info] orders-db — #42\nQuery #42 takes 120 ms on average (30,000 calls in last 24h)',
                }),
            ],
            [['1 hour', 'database time a day, worked out from the query’s pganalyze stats.']],
        ],
    ])('impact numbers %s', (_, signals, expected) => {
        expect(impactNumbers({ metrics: [] }, signals).map((number) => [number.value, number.label])).toEqual(expected)
    })

    test.each([
        [
            'the newest session, ticket or alert, not a later finding',
            [
                signal({
                    source_product: 'replay_vision',
                    timestamp: '2026-09-20T10:00:00Z',
                    extra: { session_id: 's1' },
                }),
                ticket(1042, '2026-09-25T08:00:00Z'),
                signal({ source_product: 'signals_scout', timestamp: '2026-09-30T10:00:00Z' }),
            ],
            '2026-09-25T08:00:00.000Z',
        ],
        ['nothing when no signal is an occurrence', [signal({ source_product: 'signals_scout' })], null],
    ])('dates the last occurrence as %s', (_, signals, expected) => {
        expect(lastOccurrence(signals)).toEqual(expected)
    })
})
