import { GUTTER_GAP, Y_AXIS_TITLE_MARGIN } from './hooks/useChartMargins'
import type { ChartScales, YAxisScale } from './types'
import { computeYAxisGutters } from './y-axis-gutters'

jest.mock('../utils/text-measure', () => ({ measureLabelWidth: (text: string) => text.length * 10 }))

const identity = (value: number): number => value

function scales(yAxes?: Record<string, YAxisScale>): ChartScales {
    return { x: () => 0, y: identity, yTicks: () => [1, 2, 3], yAxes }
}

const axis = (position: 'left' | 'right'): YAxisScale => ({ scale: identity, ticks: () => [0], position })

const formatters = { left: () => 'X', right: () => 'XX', right2: () => 'XXX' }

describe('computeYAxisGutters', () => {
    it('returns a single left gutter for the single-axis fallback', () => {
        const gutters = computeYAxisGutters(scales(), { yTicks: [1, 2, 3] })
        expect(gutters).toHaveLength(1)
        expect(gutters[0]).toMatchObject({ axisId: 'left', side: 'left', offset: 0 })
    })

    it('stacks same-side gutters outward, each offset by the inner gutters width plus the gap', () => {
        const gutters = computeYAxisGutters(
            scales({ left: axis('left'), right: axis('right'), right2: axis('right') }),
            {
                yTicks: [],
                yAxisFormatters: formatters,
            }
        )
        const right = gutters.find((g) => g.axisId === 'right')
        const right2 = gutters.find((g) => g.axisId === 'right2')
        expect(right).toMatchObject({ offset: 0, width: 20 })
        expect(right2?.offset).toBe(20 + GUTTER_GAP)
    })

    it('reserves a title band that pushes the next same-side gutter out', () => {
        const gutters = computeYAxisGutters(
            scales({ left: axis('left'), right: axis('right'), right2: axis('right') }),
            {
                yTicks: [],
                yAxisFormatters: formatters,
                titles: { right: 'Inner title' },
            }
        )
        const right2 = gutters.find((g) => g.axisId === 'right2')
        expect(right2?.offset).toBe(20 + GUTTER_GAP + Y_AXIS_TITLE_MARGIN)
        expect(gutters.find((g) => g.axisId === 'right')?.title).toBe('Inner title')
    })

    it('skips hidden axes entirely, so the next same-side gutter takes their slot', () => {
        const gutters = computeYAxisGutters(
            scales({ left: axis('left'), right: axis('right'), right2: axis('right') }),
            {
                yTicks: [],
                yAxisFormatters: formatters,
                hiddenAxes: { right: true },
            }
        )
        expect(gutters.map((g) => g.axisId)).toEqual(['left', 'right2'])
        const right2 = gutters.find((g) => g.axisId === 'right2')
        expect(right2).toMatchObject({ offset: 0 })
    })
})
