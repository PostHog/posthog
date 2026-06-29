import { findClosestSeriesKey } from './tooltipUtils'

const row = (key: string, yPixel?: number): { series: { key: string }; yPixel?: number } => ({
    series: { key },
    yPixel,
})

describe('findClosestSeriesKey', () => {
    it('returns null when no entry has yPixel', () => {
        expect(findClosestSeriesKey([row('a'), row('b')], 100)).toBeNull()
    })

    it('returns the key of the closest series', () => {
        expect(findClosestSeriesKey([row('a', 50), row('b', 200), row('c', 110)], 100)).toBe('c')
    })

    it('handles a single series', () => {
        expect(findClosestSeriesKey([row('x', 300)], 100)).toBe('x')
    })

    it('skips entries without yPixel', () => {
        expect(findClosestSeriesKey([row('a'), row('b', 50), row('c')], 200)).toBe('b')
    })

    it('returns null for an empty array', () => {
        expect(findClosestSeriesKey([], 100)).toBeNull()
    })

    it('prefers the first entry when distances are equal', () => {
        expect(findClosestSeriesKey([row('a', 80), row('b', 120)], 100)).toBe('a')
    })
})
