import { cleanup } from '@testing-library/react'

import { makeOverlayContext, renderOverlayInChart } from '../testing'
import { readValueBands, type ValueBandSummary } from '../testing/accessor'
import { ValueBand, type ValueBandProps } from './ValueBand'

const DIMENSIONS = { width: 800, height: 400, plotLeft: 48, plotTop: 16, plotWidth: 720, plotHeight: 352 }
const PLOT_BOTTOM = 368

describe('ValueBand', () => {
    afterEach(() => cleanup())

    it.each<[string, ValueBandProps, 'vertical' | 'horizontal', Partial<ValueBandSummary> | null]>([
        ['spans two values', { from: 100, to: 200 }, 'vertical', { top: 168, height: 100, left: 48 }],
        ['swaps an inverted pair', { from: 200, to: 100 }, 'vertical', { top: 168, height: 100 }],
        ['runs to the plot top without `to`', { from: 300 }, 'vertical', { top: 16, height: 52 }],
        ['runs to the plot bottom without `from`', { to: 100 }, 'vertical', { top: 268, height: 100 }],
        ['clamps a band that spills past the plot', { from: 300, to: 900 }, 'vertical', { top: 16 }],
        ['renders nothing wholly outside the plot', { from: 500, to: 600 }, 'vertical', null],
        // The right axis maps v to PLOT_BOTTOM - v / 2, so the band is half the height of the primary one.
        [
            'reads the axis named by yAxisId',
            { from: 100, to: 200, yAxisId: 'right' },
            'vertical',
            { top: 268, height: 50 },
        ],
        [
            'spans the value axis on a horizontal chart',
            { from: 100, to: 200 },
            'horizontal',
            { left: 148, width: 100, top: 16 },
        ],
        ['runs to the plot right on a horizontal chart', { from: 600 }, 'horizontal', { left: 648, width: 120 }],
    ])('%s', (_, props, axisOrientation, expected) => {
        const y = axisOrientation === 'vertical' ? (v: number) => PLOT_BOTTOM - v : (v: number) => 48 + v
        const right = { scale: (v: number) => PLOT_BOTTOM - v / 2, ticks: () => [], position: 'right' as const }
        const ctx = makeOverlayContext(
            { x: () => 0, y, yTicks: () => [], yAxes: { right } },
            { dimensions: DIMENSIONS, axisOrientation }
        )
        const { container } = renderOverlayInChart(<ValueBand {...props} />, ctx)
        expect(readValueBands(container)).toEqual(expected === null ? [] : [expect.objectContaining(expected)])
    })

    it.each([
        ['the theme axis color', undefined, 'rgb(1, 2, 3)'],
        ['an explicit color', 'rgb(4, 5, 6)', 'rgb(4, 5, 6)'],
    ])('fills with %s', (_, color, expected) => {
        const ctx = makeOverlayContext(
            { x: () => 0, y: (v: number) => PLOT_BOTTOM - v, yTicks: () => [] },
            { dimensions: DIMENSIONS, theme: { colors: ['#000'], axisColor: 'rgb(1, 2, 3)' } }
        )
        const { container } = renderOverlayInChart(<ValueBand from={100} to={200} color={color} />, ctx)
        expect(readValueBands(container).map((b) => b.color)).toEqual([expected])
    })
})
