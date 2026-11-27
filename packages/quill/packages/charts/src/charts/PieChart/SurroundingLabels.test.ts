import type { ResolvedSeries } from '../../core/types'
import { computePieLayout } from './computePieLayout'
import { layoutSurroundingLabels, pickSurroundingStartAngle, SURROUNDING_LEADER_SPACE } from './SurroundingLabels'

const PLOT = { plotLeft: 0, plotTop: 0, plotWidth: 800, plotHeight: 300 }

function seriesOf(values: number[]): ResolvedSeries[] {
    return values.map((v, i) => ({ key: `s${i}`, label: `Series ${i}`, data: [v], color: `#00000${i % 10}` }))
}

function place(values: number[], plot = PLOT): ReturnType<typeof layoutSurroundingLabels> {
    const layout = computePieLayout({ series: seriesOf(values), dimensions: plot, horizontalInset: 200 })
    return layoutSurroundingLabels({ layout, dimensions: plot, textFor: (slice) => ({ name: slice.series.label }) })
}

describe('layoutSurroundingLabels', () => {
    it('labels each slice in the column on its side of the pie, joined by a leader from the rim', () => {
        const layout = computePieLayout({ series: seriesOf([50, 50]), dimensions: PLOT, horizontalInset: 200 })
        const placed = layoutSurroundingLabels({
            layout,
            dimensions: PLOT,
            textFor: (slice) => ({ name: slice.series.label }),
        })

        expect(placed.map((p) => [p.key, p.side])).toEqual([
            ['s1', 'left'],
            ['s0', 'right'],
        ])
        const right = placed.find((p) => p.side === 'right')!
        expect(right.x).toBeCloseTo(layout.cx + layout.outerRadius + SURROUNDING_LEADER_SPACE)
        expect(right.points[2][1]).toBe(right.y)
        expect(Math.hypot(right.points[0][0] - layout.cx, right.points[0][1] - layout.cy)).toBeGreaterThan(
            layout.outerRadius
        )
    })

    it('spreads crowded labels apart without leaving the plot', () => {
        const placed = place([400, ...Array(12).fill(3)])

        for (const side of ['left', 'right'] as const) {
            const ys = placed.filter((p) => p.side === side).map((p) => p.y)
            for (let i = 1; i < ys.length; i++) {
                expect(ys[i] - ys[i - 1]).toBeGreaterThanOrEqual(18)
            }
            for (const y of ys) {
                expect(y).toBeGreaterThanOrEqual(PLOT.plotTop + 8)
                expect(y).toBeLessThanOrEqual(PLOT.plotTop + PLOT.plotHeight - 8)
            }
        }
        expect(placed).toHaveLength(13)
    })

    it('leaves the smallest slices unlabeled when a side has more slices than rows', () => {
        const plot = { ...PLOT, plotHeight: 100 }
        const values = [500, 100, 90, 80, 70, 60, 50, 40, 10]
        const placed = place(values, plot)

        const leftKeys = placed.filter((p) => p.side === 'left').map((p) => p.key)
        expect(leftKeys).toHaveLength(5)
        expect(new Set(leftKeys)).toEqual(new Set(['s1', 's2', 's3', 's4', 's5']))
    })

    it.each([
        ["keeps 12 o'clock when no label has to move", [50, 50], false],
        ["turns a run of thin slices away from 12 o'clock", [400, ...Array(12).fill(3)], true],
    ])('%s', (_name, values, rotated) => {
        const layoutAt = (startAngle: number): ReturnType<typeof computePieLayout> =>
            computePieLayout({
                series: seriesOf(values as number[]),
                dimensions: PLOT,
                horizontalInset: 200,
                startAngle,
            })
        const startAngle = pickSurroundingStartAngle(layoutAt, PLOT)
        expect(startAngle !== 0).toBe(rotated)

        const moved = (angle: number): number =>
            layoutSurroundingLabels({
                layout: layoutAt(angle),
                dimensions: PLOT,
                textFor: () => ({ name: '' }),
            }).reduce((sum, label) => sum + Math.abs(label.y - label.idealY), 0)
        expect(moved(startAngle)).toBeLessThanOrEqual(moved(0))
    })
})
