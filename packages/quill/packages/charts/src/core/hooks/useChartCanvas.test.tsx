import { act } from '@testing-library/react'
import React from 'react'

import { renderHogChart } from '../../testing'
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
    const { chart } = renderHogChart(
        <Chart
            series={SERIES}
            labels={LABELS}
            theme={THEME}
            createScales={createScales}
            drawStatic={drawStatic}
            drawHover={() => false}
        />
    )
    return chart.canvas
}

describe('useChartCanvas', () => {
    it('repaints against a restored backing store after the 2D context is lost', () => {
        const drawStatic = jest.fn()
        const canvas = renderChart(drawStatic)
        expect(drawStatic).toHaveBeenCalled()

        // A restored context comes back with a blank bitmap and nothing else changes — no resize,
        // no new data — so the repaint has to be driven off the event itself.
        drawStatic.mockClear()
        act(() => {
            canvas.dispatchEvent(new Event('contextrestored'))
        })

        expect(drawStatic).toHaveBeenCalled()
        // Repainting is only useful if the backing store came back with it: the handler zeroes
        // `canvas.width` to force the resize path, so a repaint that skipped restoring the size
        // would leave the canvas just as blank.
        expect(canvas.width).toBe(800)
        expect(canvas.style.width).toBe('800px')
    })
})
