import { cleanup } from '@testing-library/react'

import type { Series } from '../core/types'
import { makeOverlayContext, renderOverlayInChart } from '../testing'
import { TrendLineOverlay } from './TrendLineOverlay'

const DIMENSIONS = {
    width: 600,
    height: 300,
    plotLeft: 40,
    plotTop: 10,
    plotWidth: 520,
    plotHeight: 260,
}

// Linear y-scale: 0 -> 270 (bottom), 100 -> 10 (top)
const yScale = (v: number): number => 270 - (v / 100) * 260
// Linear x-scale: labels map to evenly spaced x positions
const xScale = (label: string): number => {
    const idx = ['A', 'B', 'C'].indexOf(label)
    return 40 + idx * 200
}

const baseContext = makeOverlayContext(
    { x: xScale, y: yScale, yTicks: () => [0, 50, 100] },
    { dimensions: DIMENSIONS, labels: ['A', 'B', 'C'] }
)

const horizontalContext = makeOverlayContext(
    { x: xScale, y: yScale, yTicks: () => [] },
    { dimensions: DIMENSIONS, labels: ['A', 'B', 'C'], axisOrientation: 'horizontal' }
)

const makeSeries = (key: string, data: number[], excluded = false): Series => ({
    key,
    label: key,
    data,
    color: '#7c3aed',
    stroke: { pattern: [6, 4] as [number, number] },
    visibility: excluded ? ({ excluded: true } as const) : undefined,
})

afterEach(cleanup)

describe('TrendLineOverlay', () => {
    it('returns null when trendSeries is empty', () => {
        const { container } = renderOverlayInChart(<TrendLineOverlay trendSeries={[]} />, baseContext)
        expect(container.querySelector('svg')).toBeNull()
    })

    it('returns null for horizontal bar charts', () => {
        const series = [makeSeries('a', [10, 50, 90])]
        const { container } = renderOverlayInChart(<TrendLineOverlay trendSeries={series} />, horizontalContext)
        expect(container.querySelector('svg')).toBeNull()
    })

    it('filters out excluded series', () => {
        const series = [makeSeries('visible', [10, 50, 90]), makeSeries('hidden', [5, 25, 45], true)]
        const { container } = renderOverlayInChart(<TrendLineOverlay trendSeries={series} />, baseContext)
        const polylines = container.querySelectorAll('polyline')
        expect(polylines).toHaveLength(1)
    })

    it('renders one SVG polyline per visible series', () => {
        const series = [makeSeries('a', [10, 50, 90]), makeSeries('b', [90, 50, 10])]
        const { container } = renderOverlayInChart(<TrendLineOverlay trendSeries={series} />, baseContext)
        expect(container.querySelector('svg')).not.toBeNull()
        expect(container.querySelectorAll('polyline')).toHaveLength(2)
    })

    it('uses the series stroke pattern as the SVG dash array', () => {
        const series = [makeSeries('a', [10, 50, 90])]
        const { container } = renderOverlayInChart(<TrendLineOverlay trendSeries={series} />, baseContext)
        const polyline = container.querySelector('polyline')
        expect(polyline?.getAttribute('stroke-dasharray')).toBe('6,4')
    })

    it('renders a non-interactive SVG overlay', () => {
        const series = [makeSeries('a', [10, 50, 90])]
        const { container } = renderOverlayInChart(<TrendLineOverlay trendSeries={series} />, baseContext)
        const svg = container.querySelector('svg')
        expect(svg).not.toBeNull()
        expect(svg?.style.pointerEvents).toBe('none')
    })
})
