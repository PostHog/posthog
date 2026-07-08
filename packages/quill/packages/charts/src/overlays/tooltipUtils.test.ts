import { findClosestSeriesKey } from './tooltipUtils'

const row = (key: string, yPixel?: number): { series: { key: string }; yPixel?: number } => ({
    series: { key },
    yPixel,
})

// Stacked segment: yPixel = top pixel (smaller y = higher on screen), yPixelBottom = bottom pixel.
const segment = (
    key: string,
    yPixel: number,
    yPixelBottom: number
): { series: { key: string }; yPixel: number; yPixelBottom: number } => ({
    series: { key },
    yPixel,
    yPixelBottom,
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

    describe('range containment (stacked bar segments)', () => {
        // Three stacked segments in canvas coordinates (y=0 at top, increases downward):
        //   A (bottom): top=150, bottom=300  →  spans y 150..300
        //   B (middle): top=75,  bottom=150  →  spans y 75..150
        //   C (top):    top=0,   bottom=75   →  spans y 0..75
        const segs = [segment('a', 150, 300), segment('b', 75, 150), segment('c', 0, 75)]

        it.each([
            // Cursor clearly inside each segment
            [250, 'a'],
            [112, 'b'],
            [30, 'c'],
            // Near boundaries but still inside
            [151, 'a'],
            [149, 'b'],
        ])('cursor y=%i → %s', (cursorY, expected) => {
            expect(findClosestSeriesKey(segs, cursorY)).toBe(expected)
        })

        it('catches the dead-zone bug: cursor near top of a tall lower segment still picks that segment', () => {
            // Without range containment, cursor at y=160 (inside A, range 150..300) would pick B
            // because B's midpoint (112) is closer than A's midpoint (225). Range containment fixes this.
            expect(findClosestSeriesKey(segs, 160)).toBe('a')
        })

        it('falls back to distance when cursor is outside all ranges', () => {
            // Cursor above all segments — picks the topmost (C, top=0) by distance.
            expect(findClosestSeriesKey(segs, -10)).toBe('c')
        })

        it('ignores yPixelBottom for entries that lack it, using distance fallback for those', () => {
            // Mix of range and non-range rows — range rows win when cursor is inside them.
            const mixed = [row('dist', 50), segment('range', 200, 300)]
            expect(findClosestSeriesKey(mixed, 250)).toBe('range')
        })
    })
})
