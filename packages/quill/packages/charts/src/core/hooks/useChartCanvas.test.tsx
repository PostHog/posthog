import { act, render } from '@testing-library/react'
import React from 'react'

import { ensureJsdom } from '../../testing'
import { Chart } from '../Chart'
import type { ChartDrawArgs, ChartScales, ChartTheme, Series } from '../types'

const THEME: ChartTheme = { colors: ['#f00'], gridColor: '#eee', crosshairColor: '#888' }

const SERIES: Series[] = [{ key: 'a', label: 'A', data: [10, 20, 30] }]

const LABELS = ['Mon', 'Tue', 'Wed']

const createScales = (): ChartScales => ({
    x: () => 100,
    y: (value: number) => 200 - value,
    yTicks: () => [0, 50, 100],
})

function renderChart(drawStatic: (args: ChartDrawArgs) => void): HTMLCanvasElement {
    ensureJsdom()
    const { container } = render(
        <Chart
            series={SERIES}
            labels={LABELS}
            theme={THEME}
            createScales={createScales}
            drawStatic={drawStatic}
            drawHover={() => false}
        />
    )
    return container.querySelector('canvas')!
}

describe('useChartCanvas', () => {
    it('repaints after a lost 2D context is restored', () => {
        const drawStatic = jest.fn()
        const canvas = renderChart(drawStatic)
        expect(drawStatic).toHaveBeenCalled()

        // A restored context comes back with a blank bitmap and nothing else changes — no resize, no
        // new data — so without this the canvas stays empty while every DOM overlay keeps rendering.
        drawStatic.mockClear()
        act(() => {
            canvas.dispatchEvent(new Event('contextrestored'))
        })

        expect(drawStatic).toHaveBeenCalled()
    })
})
