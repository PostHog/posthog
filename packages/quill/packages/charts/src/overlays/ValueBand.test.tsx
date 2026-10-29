import { cleanup } from '@testing-library/react'

import { makeOverlayContext, renderOverlayInChart } from '../testing'
import { ValueBand, type ValueBandProps } from './ValueBand'

const DIMENSIONS = { width: 800, height: 400, plotLeft: 48, plotTop: 16, plotWidth: 720, plotHeight: 352 }
const PLOT_BOTTOM = 368

describe('ValueBand', () => {
    afterEach(() => cleanup())

    it.each<[string, ValueBandProps, 'vertical' | 'horizontal', Record<string, string> | null]>([
        ['spans two values', { from: 100, to: 200 }, 'vertical', { top: '168px', height: '100px', left: '48px' }],
        ['runs to the plot top without `to`', { from: 300 }, 'vertical', { top: '16px', height: '52px' }],
        ['runs to the plot bottom without `from`', { to: 100 }, 'vertical', { top: '268px', height: '100px' }],
        ['clamps a band that spills past the plot', { from: 300, to: 900 }, 'vertical', { top: '16px' }],
        ['renders nothing wholly outside the plot', { from: 500, to: 600 }, 'vertical', null],
        [
            'spans the value axis on a horizontal chart',
            { from: 100, to: 200 },
            'horizontal',
            { left: '148px', width: '100px', top: '16px' },
        ],
        [
            'runs to the plot right on a horizontal chart',
            { from: 600 },
            'horizontal',
            { left: '648px', width: '120px' },
        ],
    ])('%s', (_, props, axisOrientation, expected) => {
        const y = axisOrientation === 'vertical' ? (v: number) => PLOT_BOTTOM - v : (v: number) => 48 + v
        const ctx = makeOverlayContext({ x: () => 0, y, yTicks: () => [] }, { dimensions: DIMENSIONS, axisOrientation })
        const { container } = renderOverlayInChart(<ValueBand {...props} />, ctx)
        const band = container.querySelector<HTMLDivElement>('[data-attr="hog-chart-value-band"]')
        if (expected === null) {
            expect(band).toBeNull()
        } else {
            expect(band?.style).toMatchObject(expected)
        }
    })
})
