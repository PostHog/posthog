import { dailyTrend } from './todayImpact'

describe('todayImpact', () => {
    test.each([
        [
            'starts at the first day with a value',
            { series: [0, 0, 3, 5], value_at: '2026-10-01T12:00:00Z', query: { source: { interval: 'day' } } },
            { data: [3, 5], since: '30 Sep', start: '2026-09-30' },
        ],
        [
            'dates a series that has a value from its first day',
            { series: [2, 0, 3], value_at: '2026-10-01T12:00:00Z', query: { source: { interval: 'day' } } },
            { data: [2, 0, 3], since: null, start: '2026-09-29' },
        ],
        [
            'keeps the whole window when it is not daily',
            { series: [0, 2, 3], value_at: '2026-10-01T12:00:00Z', query: { source: { interval: 'week' } } },
            { data: [0, 2, 3], since: null, start: null },
        ],
    ])('builds a daily trend that %s', (_, metric, expected) => {
        expect(dailyTrend(metric as never)).toEqual(expected)
    })
})
