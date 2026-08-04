import { resolveMarkerX } from './BillingPeriodMarkers'

describe('resolveMarkerX', () => {
    // Three evenly spaced monthly buckets at 100px intervals.
    const labelTimestamps = [
        Date.UTC(2026, 0, 1), // Jan 1
        Date.UTC(2026, 1, 1), // Feb 1
        Date.UTC(2026, 2, 1), // Mar 1
    ]
    const labelX = [0, 100, 200]

    it('places a marker sitting exactly on a label at that label', () => {
        expect(resolveMarkerX(labelTimestamps[1], labelTimestamps, labelX)).toBe(100)
    })

    it('interpolates a marker that falls between two labels', () => {
        // Jan 16 is roughly halfway through the 31-day January bucket.
        const x = resolveMarkerX(Date.UTC(2026, 0, 16), labelTimestamps, labelX)
        expect(x).toBeGreaterThan(45)
        expect(x).toBeLessThan(55)
    })

    it.each([
        ['before the first label', Date.UTC(2025, 11, 15)],
        ['after the last label', Date.UTC(2026, 2, 2)],
    ])('returns null for a marker %s', (_, markerTs) => {
        expect(resolveMarkerX(markerTs, labelTimestamps, labelX)).toBeNull()
    })

    it('resolves an exact match on a single-bucket chart, which has no interval to interpolate', () => {
        const single = [Date.UTC(2026, 0, 1)]
        expect(resolveMarkerX(single[0], single, [42])).toBe(42)
        expect(resolveMarkerX(Date.UTC(2026, 0, 2), single, [42])).toBeNull()
    })
})
