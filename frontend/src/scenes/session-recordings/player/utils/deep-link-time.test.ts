import { DeepLinkTime, parseDeepLinkTime } from './deep-link-time'

describe('parseDeepLinkTime', () => {
    // 2026-09-01T10:00:30.000Z
    const isoDate = '2026-09-01T10:00:30.000Z'
    const isoMs = Date.parse(isoDate)

    const cases: {
        name: string
        timestamp?: string | number
        t?: string | number
        expected: DeepLinkTime | null
    }[] = [
        { name: 'no params', timestamp: undefined, t: undefined, expected: null },
        {
            // kea-router coerces a numeric query param to a number, so `t.trim()` must not be assumed.
            name: 'numeric t is a seconds offset',
            timestamp: undefined,
            t: 30,
            expected: { kind: 'offset', valueMs: 30000 },
        },
        {
            name: 'numeric timestamp is absolute unix ms',
            timestamp: 1756720830000,
            t: undefined,
            expected: { kind: 'timestamp', valueMs: 1756720830000 },
        },
        {
            // Regression: the Slack destination docs emit an ISO date in `t`, which used to
            // yield NaN and start the recording from the beginning (issue #90565).
            name: 'ISO date in t is an absolute timestamp',
            timestamp: undefined,
            t: isoDate,
            expected: { kind: 'timestamp', valueMs: isoMs },
        },
        {
            name: 'ISO date in timestamp is an absolute timestamp',
            timestamp: isoDate,
            t: undefined,
            expected: { kind: 'timestamp', valueMs: isoMs },
        },
        { name: 'unparseable t', timestamp: undefined, t: 'not-a-time', expected: null },
        { name: 'zone-less datetime in t', timestamp: undefined, t: '2026-09-01T10:00:30', expected: null },
        { name: 'date-only t', timestamp: undefined, t: '2026-09-01', expected: null },
        {
            name: 'timestamp wins over t when both are present',
            timestamp: 1756720830000,
            t: 30,
            expected: { kind: 'timestamp', valueMs: 1756720830000 },
        },
    ]

    it.each(cases)('$name', ({ timestamp, t, expected }) => {
        expect(parseDeepLinkTime(timestamp, t)).toEqual(expected)
    })
})
