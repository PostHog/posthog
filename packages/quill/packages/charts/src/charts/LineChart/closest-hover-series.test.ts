import type { ResolvedSeries } from '../../core/types'
import { closestHoverSeriesKey } from './closest-hover-series'

const series = (key: string, overrides: Partial<ResolvedSeries> = {}): ResolvedSeries => ({
    key,
    label: key,
    color: '#000',
    data: [],
    ...overrides,
})

// y-pixels keyed by series.key, so each test controls how far each line sits from the cursor.
const yPixelFromMap =
    (map: Record<string, number>) =>
    (s: ResolvedSeries): number =>
        map[s.key] ?? NaN

describe('closestHoverSeriesKey', () => {
    it('picks the series whose y-pixel is nearest the cursor', () => {
        const result = closestHoverSeriesKey(
            [series('a'), series('b'), series('c')],
            yPixelFromMap({ a: 10, b: 100, c: 40 }),
            45
        )
        expect(result).toBe('c')
    })

    it('skips excluded, fill-between lower-bound, and overlay series even when they are nearest', () => {
        // The off-limits series all sit exactly on the cursor; the only eligible one is far away
        // but must still win.
        const result = closestHoverSeriesKey(
            [
                series('hidden', { visibility: { excluded: true } }),
                series('lower', { fill: { lowerData: [1, 2, 3] } }),
                series('trend', { overlay: true }),
                series('real', {}),
            ],
            yPixelFromMap({ hidden: 50, lower: 50, trend: 50, real: 200 }),
            50
        )
        expect(result).toBe('real')
    })

    it('ignores series with a non-finite y-pixel (off-plot / collapsed cell)', () => {
        const result = closestHoverSeriesKey(
            [series('a'), series('b')],
            yPixelFromMap({ a: NaN, b: 300 }),
            0
        )
        expect(result).toBe('b')
    })

    it('returns null when no series qualifies', () => {
        const result = closestHoverSeriesKey(
            [series('only', { overlay: true }), series('nan')],
            yPixelFromMap({ only: 10, nan: NaN }),
            10
        )
        expect(result).toBeNull()
    })

    it('keeps the first series on a distance tie (strict less-than)', () => {
        const result = closestHoverSeriesKey([series('a'), series('b')], yPixelFromMap({ a: 30, b: 70 }), 50)
        expect(result).toBe('a')
    })
})
