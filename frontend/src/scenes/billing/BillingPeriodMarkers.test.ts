import { resolveMarkerX } from './BillingPeriodMarkers'

describe('resolveMarkerX', () => {
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
        // Jan 16 is 15 days into the 31-day January bucket: (15 / 31) * 100 = 48.387...
        const x = resolveMarkerX(Date.UTC(2026, 0, 16), labelTimestamps, labelX)
        expect(x).toBeCloseTo((15 / 31) * 100, 5)
    })

    it.each([
        ['before the first label', Date.UTC(2025, 11, 15)],
        ['after the last label', Date.UTC(2026, 2, 2)],
    ])('returns null for a marker %s', (_, markerTs) => {
        expect(resolveMarkerX(markerTs, labelTimestamps, labelX)).toBeNull()
    })

    it.each([
        ['on the first label', Date.UTC(2026, 0, 1), 0],
        ['on the last label', Date.UTC(2026, 2, 1), 200],
    ])('resolves a marker landing exactly %s as an in-range x', (_, markerTs, expectedX) => {
        expect(resolveMarkerX(markerTs, labelTimestamps, labelX)).toBe(expectedX)
    })

    it('resolves an exact match on a single-bucket chart, which has no interval to interpolate', () => {
        const single = [Date.UTC(2026, 0, 1)]
        expect(resolveMarkerX(single[0], single, [42])).toBe(42)
        expect(resolveMarkerX(Date.UTC(2026, 0, 2), single, [42])).toBeNull()
    })
})
