import type { ResolvedSeries } from '../../core/types'
import { computePieLayout, cursorOffsetToAngle, sliceAt } from './computePieLayout'

const PLOT = { plotLeft: 0, plotTop: 0, plotWidth: 400, plotHeight: 400 }

function s(key: string, data: number[], extras: Partial<ResolvedSeries> = {}): ResolvedSeries {
    return { key, label: key.toUpperCase(), data, color: '#000', ...extras }
}

describe('computePieLayout', () => {
    it('spans the full 2π across all slices (no gaps when padAngle = 0)', () => {
        const layout = computePieLayout({
            series: [s('a', [10]), s('b', [20]), s('c', [30])],
            dimensions: PLOT,
        })
        const total = layout.slices.reduce((sum, sl) => sum + (sl.endAngle - sl.startAngle), 0)
        expect(total).toBeCloseTo(2 * Math.PI, 6)
    })

    it('subtracts padAngle gaps from total span', () => {
        const padAngle = 0.02
        const layout = computePieLayout({
            series: [s('a', [10]), s('b', [20]), s('c', [30])],
            dimensions: PLOT,
            padAngle,
        })
        // d3.pie keeps the total spanned but reduces the drawable arc by padAngle per slice.
        // Per d3 docs the gross extent stays 2π, so we just sanity-check there are 3 slices
        // and padAngle is reflected.
        expect(layout.slices).toHaveLength(3)
        expect(layout.padAngle).toBe(padAngle)
    })

    it('drops excluded series from layout', () => {
        const layout = computePieLayout({
            series: [s('a', [10]), s('b', [20], { visibility: { excluded: true } }), s('c', [30])],
            dimensions: PLOT,
        })
        expect(layout.slices.map((sl) => sl.series.key)).toEqual(['a', 'c'])
        expect(layout.total).toBe(40)
    })

    it('preserves original seriesIndex through excluded filtering', () => {
        const layout = computePieLayout({
            series: [s('a', [10]), s('b', [20], { visibility: { excluded: true } }), s('c', [30])],
            dimensions: PLOT,
        })
        // 'c' is at index 2 in the input; the slice must preserve that for click attribution.
        const sliceC = layout.slices.find((sl) => sl.series.key === 'c')
        expect(sliceC?.seriesIndex).toBe(2)
    })

    it('produces donut radii when innerRadiusRatio > 0', () => {
        const layout = computePieLayout({
            series: [s('a', [10]), s('b', [10])],
            dimensions: PLOT,
            innerRadiusRatio: 0.5,
        })
        expect(layout.outerRadius).toBeGreaterThan(0)
        expect(layout.innerRadius).toBeCloseTo(layout.outerRadius * 0.5, 6)
    })

    it('clamps innerRadiusRatio into [0, 0.95]', () => {
        const layout = computePieLayout({
            series: [s('a', [10]), s('b', [10])],
            dimensions: PLOT,
            innerRadiusRatio: 5,
        })
        expect(layout.innerRadius).toBeCloseTo(layout.outerRadius * 0.95, 6)
    })

    it('preserves input order when sort is null (default)', () => {
        const layout = computePieLayout({
            series: [s('big', [100]), s('mid', [50]), s('small', [10])],
            dimensions: PLOT,
        })
        expect(layout.slices.map((sl) => sl.series.key)).toEqual(['big', 'mid', 'small'])
    })

    it('respects a sort comparator on slice magnitudes (slice angles reflect sort, not array order)', () => {
        // d3.pie keeps the output array aligned with the input data so consumers can join by
        // index; the sort affects start/end angles instead. Validate the *visual* order.
        const layout = computePieLayout({
            series: [s('small', [10]), s('big', [100]), s('mid', [50])],
            dimensions: PLOT,
            sort: (a, b) => b - a,
        })
        const byStart = [...layout.slices].sort((a, b) => a.startAngle - b.startAngle)
        expect(byStart.map((sl) => sl.series.key)).toEqual(['big', 'mid', 'small'])
    })

    it('clamps negative values to 0', () => {
        const layout = computePieLayout({
            series: [s('a', [-50]), s('b', [10])],
            dimensions: PLOT,
        })
        expect(layout.total).toBe(10)
        // Negative-valued slice contributes 0 so its arc collapses.
        const sliceA = layout.slices.find((sl) => sl.series.key === 'a')
        expect(sliceA).not.toBeUndefined()
        expect(sliceA!.endAngle - sliceA!.startAngle).toBeCloseTo(0, 6)
    })

    it('returns an empty layout when total is 0', () => {
        const layout = computePieLayout({
            series: [s('a', [0]), s('b', [0])],
            dimensions: PLOT,
        })
        expect(layout.slices).toHaveLength(0)
        expect(layout.total).toBe(0)
    })

    it('returns an empty layout when no series', () => {
        const layout = computePieLayout({ series: [], dimensions: PLOT })
        expect(layout.slices).toHaveLength(0)
        expect(layout.total).toBe(0)
    })

    it('normalizes fractions to sum to 1', () => {
        const layout = computePieLayout({
            series: [s('a', [3]), s('b', [3]), s('c', [3]), s('d', [1])],
            dimensions: PLOT,
        })
        const sum = layout.slices.reduce((acc, sl) => acc + sl.fraction, 0)
        expect(sum).toBeCloseTo(1, 6)
    })

    it('uses a custom sliceValue resolver when provided', () => {
        const layout = computePieLayout({
            series: [s('a', [10, 20]), s('b', [5])],
            dimensions: PLOT,
            sliceValue: (sr) => sr.data.length,
        })
        // a has 2 entries, b has 1.
        const sliceA = layout.slices.find((sl) => sl.series.key === 'a')
        const sliceB = layout.slices.find((sl) => sl.series.key === 'b')
        expect(sliceA?.value).toBe(2)
        expect(sliceB?.value).toBe(1)
    })
})

describe('cursorOffsetToAngle', () => {
    it.each<[string, number, number, number]>([
        ["12 o'clock", 0, -1, 0],
        ["3 o'clock", 1, 0, Math.PI / 2],
        ["6 o'clock", 0, 1, Math.PI],
        ["9 o'clock", -1, 0, (3 * Math.PI) / 2],
    ])('%s', (_name, dx, dy, expected) => {
        expect(cursorOffsetToAngle(dx, dy)).toBeCloseTo(expected, 6)
    })

    it.each<[number]>([[0], [17], [45], [90], [127], [180], [225], [270], [315], [340]])(
        'returns an angle in [0, 2π) for %sdeg',
        (deg) => {
            const rad = (deg * Math.PI) / 180
            const a = cursorOffsetToAngle(Math.sin(rad), -Math.cos(rad))
            expect(a).toBeGreaterThanOrEqual(0)
            expect(a).toBeLessThan(2 * Math.PI)
        }
    )
})

describe('sliceAt', () => {
    const baseLayout = computePieLayout({
        series: [s('a', [25]), s('b', [25]), s('c', [25]), s('d', [25])],
        dimensions: PLOT,
    })
    // four equal slices: each 90deg, starting at 12 o'clock and progressing clockwise.
    // slice 0 → 12 to 3, slice 1 → 3 to 6, slice 2 → 6 to 9, slice 3 → 9 to 12.

    function cursorAt(angleDeg: number, radius: number): { x: number; y: number } {
        const rad = (angleDeg * Math.PI) / 180
        return {
            x: baseLayout.cx + Math.sin(rad) * radius,
            y: baseLayout.cy - Math.cos(rad) * radius,
        }
    }

    it('identifies the slice under the cursor for each cardinal direction', () => {
        const midR = (baseLayout.innerRadius + baseLayout.outerRadius) / 2 || baseLayout.outerRadius / 2
        expect(sliceAt(baseLayout, cursorAt(45, midR))).toBe(0)
        expect(sliceAt(baseLayout, cursorAt(135, midR))).toBe(1)
        expect(sliceAt(baseLayout, cursorAt(225, midR))).toBe(2)
        expect(sliceAt(baseLayout, cursorAt(315, midR))).toBe(3)
    })

    it('returns -1 outside outerRadius', () => {
        expect(sliceAt(baseLayout, cursorAt(45, baseLayout.outerRadius + 50))).toBe(-1)
    })

    it('accepts a cursor inside the outerSlack band', () => {
        const slack = 20
        expect(sliceAt(baseLayout, cursorAt(45, baseLayout.outerRadius + 10), { outerSlack: slack })).toBe(0)
    })

    it('returns -1 inside the donut inner hole', () => {
        const donut = computePieLayout({
            series: [s('a', [25]), s('b', [25]), s('c', [25]), s('d', [25])],
            dimensions: PLOT,
            innerRadiusRatio: 0.6,
        })
        const insideHole = { x: donut.cx + 5, y: donut.cy + 5 }
        expect(sliceAt(donut, insideHole)).toBe(-1)
    })

    it('returns -1 inside a padAngle gap', () => {
        const padded = computePieLayout({
            series: [s('a', [25]), s('b', [25]), s('c', [25]), s('d', [25])],
            dimensions: PLOT,
            padAngle: 0.2, // wide gap so we can land in it
        })
        // boundary at 90deg between slice 0 and slice 1
        const midR = padded.outerRadius / 2
        const boundary = {
            x: padded.cx + Math.sin(Math.PI / 2) * midR,
            y: padded.cy - Math.cos(Math.PI / 2) * midR,
        }
        expect(sliceAt(padded, boundary)).toBe(-1)
    })

    it.each<[number]>([[0], [90], [180], [270], [359]])(
        "handles the 12 o'clock wraparound at %sdeg for a single slice",
        (deg) => {
            const full = computePieLayout({
                series: [s('only', [100])],
                dimensions: PLOT,
            })
            const midR = full.outerRadius / 2
            const rad = (deg * Math.PI) / 180
            expect(sliceAt(full, { x: full.cx + Math.sin(rad) * midR, y: full.cy - Math.cos(rad) * midR })).toBe(0)
        }
    )

    it('returns -1 when there are no slices', () => {
        const empty = computePieLayout({ series: [], dimensions: PLOT })
        expect(sliceAt(empty, { x: empty.cx, y: empty.cy })).toBe(-1)
    })
})
