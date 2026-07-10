import { dateRangeZoomEnd } from './hooks'

describe('dateRangeZoomEnd', () => {
    it.each([
        // Bucket starts must widen to the bucket's end, else a zoom keeps only the last
        // bucket's first day/instant.
        ['month', '2024-04-01', '2024-04-30'],
        ['week', '2024-06-09', '2024-06-15'],
        ['hour', '2024-06-10 08:00:00', '2024-06-10 08:59:59'],
        // A bare date already spans the whole day — no widening.
        ['day', '2024-06-13', '2024-06-13'],
        // Non-date x values (e.g. arbitrary SQL columns) pass through untouched.
        ['month', 'not-a-date', 'not-a-date'],
    ] as const)('widens a %s bucket start %s to %s', (interval, bucketStart, expected) => {
        expect(dateRangeZoomEnd(bucketStart, interval)).toBe(expected)
    })

    it('returns the start unchanged when the interval is unknown', () => {
        expect(dateRangeZoomEnd('2024-04-01', null)).toBe('2024-04-01')
        expect(dateRangeZoomEnd('2024-04-01', undefined)).toBe('2024-04-01')
    })
})
