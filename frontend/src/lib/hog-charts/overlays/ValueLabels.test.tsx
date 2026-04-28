import { cleanup, render } from '@testing-library/react'
import React from 'react'

import type { BaseChartContext, ChartLayoutContextValue } from '../core/chart-context'
import { ChartHoverContext, ChartLayoutContext } from '../core/chart-context'
import type { ChartTheme, ResolveValueFn, Series } from '../core/types'
import { ValueLabels } from './ValueLabels'

const DIMENSIONS = {
    width: 800,
    height: 400,
    plotLeft: 48,
    plotTop: 16,
    plotWidth: 720,
    plotHeight: 352,
}

const LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
const X_POSITIONS: Record<string, number> = { Mon: 60, Tue: 220, Wed: 380, Thu: 540, Fri: 700 }

const xScale = (label: string): number | undefined => X_POSITIONS[label]
// Left axis: 0 -> 368, 100 -> 16
const yScale = (v: number): number => 368 - (v / 100) * 352

const DEFAULT_THEME: ChartTheme = { colors: ['#000'], backgroundColor: '#ffffff' }
const DEFAULT_RESOLVE: ResolveValueFn = (s, i) => s.data[i] ?? 0

function makeContext(series: Series[], overrides: Partial<BaseChartContext> = {}): BaseChartContext {
    return {
        dimensions: DIMENSIONS,
        labels: LABELS,
        series,
        scales: {
            x: xScale,
            y: yScale,
            yTicks: () => [0, 50, 100],
        },
        theme: DEFAULT_THEME,
        resolveValue: DEFAULT_RESOLVE,
        canvasBounds: () => null,
        hoverIndex: -1,
        ...overrides,
    }
}

function toLayout(ctx: BaseChartContext): ChartLayoutContextValue {
    const { hoverIndex: _hoverIndex, ...layout } = ctx
    return layout
}

function renderInChart(context: BaseChartContext, node: React.ReactNode): ReturnType<typeof render> {
    return render(
        <ChartLayoutContext.Provider value={toLayout(context)}>
            <ChartHoverContext.Provider value={{ hoverIndex: context.hoverIndex }}>{node}</ChartHoverContext.Provider>
        </ChartLayoutContext.Provider>
    )
}

function labelDivs(container: HTMLElement): HTMLDivElement[] {
    return Array.from(container.querySelectorAll<HTMLDivElement>('[data-attr="hog-chart-value-label"]'))
}

describe('ValueLabels', () => {
    afterEach(() => cleanup())

    it('renders one label per non-zero data point in a single series', () => {
        const series: Series[] = [{ key: 's', label: 'S', color: '#f00', data: [10, 20, 30, 40, 50] }]
        const { container } = renderInChart(makeContext(series), <ValueLabels />)
        const divs = labelDivs(container)
        expect(divs).toHaveLength(5)
        expect(divs.map((d) => d.textContent)).toEqual(['10', '20', '30', '40', '50'])
    })

    it.each<[string, ((value: number) => string) | undefined, number[], string[]]>([
        ['no formatter → toLocaleString', undefined, [1234, 5678], [(1234).toLocaleString(), (5678).toLocaleString()]],
        ['custom formatter', (v) => `$${(v / 1000).toFixed(1)}k`, [1000, 2000], ['$1.0k', '$2.0k']],
    ])('formats labels: %s', (_name, formatter, data, expected) => {
        const series: Series[] = [{ key: 's', label: 'S', color: '#f00', data }]
        const ctx = makeContext(series, { labels: ['Mon', 'Tue'] })
        const { container } = renderInChart(ctx, <ValueLabels valueFormatter={formatter} />)
        const divs = labelDivs(container)
        expect(divs.map((d) => d.textContent)).toEqual(expected)
    })

    it('renders zero values as legitimate data points', () => {
        const series: Series[] = [{ key: 's', label: 'S', color: '#f00', data: [10, 0, 30, 0, 50] }]
        const { container } = renderInChart(makeContext(series), <ValueLabels />)
        expect(labelDivs(container).map((d) => d.textContent)).toEqual(['10', '0', '30', '0', '50'])
    })

    it('skips non-finite values (NaN, Infinity)', () => {
        const series: Series[] = [{ key: 's', label: 'S', color: '#f00', data: [10, NaN, 30, Infinity, 50] }]
        const { container } = renderInChart(makeContext(series), <ValueLabels />)
        expect(labelDivs(container).map((d) => d.textContent)).toEqual(['10', '30', '50'])
    })

    it('skips series where visibility.excluded is true', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', color: '#f00', data: [10, 20, 30, 40, 50] },
            { key: 'b', label: 'B', color: '#0f0', data: [60, 70, 80, 90, 100], visibility: { excluded: true } },
        ]
        const { container } = renderInChart(makeContext(series), <ValueLabels />)
        const divs = labelDivs(container)
        expect(divs).toHaveLength(5)
        divs.forEach((d) => expect(d.style.backgroundColor).toBe('rgb(255, 0, 0)'))
    })

    it('positions negative values below the point and positive values above', () => {
        const series: Series[] = [{ key: 's', label: 'S', color: '#f00', data: [50, -50, 25, -25, 75] }]
        const { container } = renderInChart(makeContext(series), <ValueLabels />)
        const divs = labelDivs(container)
        expect(divs).toHaveLength(5)
        // positive values (50, 25, 75) render above → transform includes 'calc(-100%'
        // negative values (-50, -25) render below → transform is plain translateX
        const values = [50, -50, 25, -25, 75]
        divs.forEach((d, i) => {
            const value = values[i]
            if (value >= 0) {
                expect(d.style.transform).toContain('calc(-100%')
            } else {
                expect(d.style.transform).toBe('translateX(-50%)')
            }
        })
    })

    it('skips a series with more points than maxPointsPerSeries', () => {
        const longData = Array.from({ length: 150 }, (_, i) => i + 1)
        const longLabels = longData.map((_, i) => `L${i}`)
        const longXPositions: Record<string, number> = {}
        longData.forEach((_, i) => {
            longXPositions[`L${i}`] = 60 + (i / (longData.length - 1)) * 640
        })
        const series: Series[] = [{ key: 's', label: 'S', color: '#f00', data: longData }]
        const ctx = makeContext(series, {
            labels: longLabels,
            scales: {
                x: (label: string) => longXPositions[label],
                y: yScale,
                yTicks: () => [0, 50, 100],
            },
        })
        const { container } = renderInChart(ctx, <ValueLabels />)
        expect(labelDivs(container)).toHaveLength(0)
    })

    it('honours a custom maxPointsPerSeries override', () => {
        const data = Array.from({ length: 6 }, (_, i) => 10 + i * 10)
        const series: Series[] = [{ key: 's', label: 'S', color: '#f00', data }]
        // default (100) renders all; override to 3 should render none
        const ctx = makeContext(series)
        const { container } = renderInChart(ctx, <ValueLabels maxPointsPerSeries={3} />)
        expect(labelDivs(container)).toHaveLength(0)
    })

    it('drops overlapping labels via greedy collision avoidance', () => {
        // Two points at the same x: only one should survive.
        const series: Series[] = [{ key: 's', label: 'S', color: '#f00', data: [50, 50] }]
        const ctx = makeContext(series, {
            labels: ['A', 'B'],
            scales: {
                // both points sit at x=100 → guaranteed collision
                x: () => 100,
                y: yScale,
                yTicks: () => [0, 50, 100],
            },
        })
        const { container } = renderInChart(ctx, <ValueLabels />)
        expect(labelDivs(container)).toHaveLength(1)
    })

    it('uses the matching yAxes scale when a series has a yAxisId', () => {
        // Right axis maps 0-1000; left axis maps 0-100.
        const rightScale = (v: number): number => 368 - (v / 1000) * 352
        const series: Series[] = [{ key: 'right', label: 'R', color: '#00f', data: [500], yAxisId: 'y1' }]
        const ctx = makeContext(series, {
            labels: ['Mon'],
            scales: {
                x: xScale,
                y: yScale,
                yTicks: () => [0, 50, 100],
                yAxes: {
                    left: { scale: yScale, ticks: () => [0, 50, 100], position: 'left' },
                    y1: { scale: rightScale, ticks: () => [0, 500, 1000], position: 'right' },
                },
            },
        })
        const { container } = renderInChart(ctx, <ValueLabels />)
        const divs = labelDivs(container)
        expect(divs).toHaveLength(1)
        // rightScale(500) = 192 → label top should match (positive → 'above' case uses top=y exactly)
        expect(divs[0].style.top).toBe('192px')
    })

    it('falls back to the primary y-scale when yAxisId is unknown', () => {
        const series: Series[] = [{ key: 's', label: 'S', color: '#f00', data: [50], yAxisId: 'missing' }]
        const ctx = makeContext(series, { labels: ['Mon'] })
        const { container } = renderInChart(ctx, <ValueLabels />)
        const divs = labelDivs(container)
        expect(divs).toHaveLength(1)
        // yScale(50) = 192
        expect(divs[0].style.top).toBe('192px')
    })

    it('renders one label per series at the same x, each with its own color', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', color: '#112233', data: [10] },
            { key: 'b', label: 'B', color: '#445566', data: [20] },
        ]
        const ctx = makeContext(series, { labels: ['Mon'] })
        // Collision avoidance is per-series so both labels should render.
        const { container } = renderInChart(ctx, <ValueLabels />)
        const divs = labelDivs(container)
        expect(divs).toHaveLength(2)
        const bgColors = divs.map((d) => d.style.backgroundColor).sort()
        expect(bgColors).toEqual(['rgb(17, 34, 51)', 'rgb(68, 85, 102)'])
    })

    it('renders null when nothing survives filtering', () => {
        const series: Series[] = [{ key: 's', label: 'S', color: '#f00', data: [NaN, NaN, NaN] }]
        const ctx = makeContext(series, { labels: ['Mon', 'Tue', 'Wed'] })
        const { container } = renderInChart(ctx, <ValueLabels />)
        expect(labelDivs(container)).toHaveLength(0)
    })

    it('positions labels at the resolved (e.g. stacked) y, not the raw series.data y', () => {
        // Raw value 25 sits at y=278 on the left axis; stacking lifts it to top-of-stack=75 → y=104.
        // The resolveValue closure mimics what LineChart provides for stacked series.
        const series: Series[] = [{ key: 's', label: 'S', color: '#f00', data: [25] }]
        const stackedTops: Record<string, number[]> = { s: [75] }
        const resolveValue: ResolveValueFn = (s, i) => stackedTops[s.key]?.[i] ?? s.data[i] ?? 0
        const ctx = makeContext(series, { labels: ['Mon'], resolveValue })
        const { container } = renderInChart(ctx, <ValueLabels />)
        const divs = labelDivs(container)
        expect(divs).toHaveLength(1)
        // Label text comes from the raw value (25), but position uses the resolved 75.
        expect(divs[0].textContent).toBe('25')
        // yScale(75) = 368 - (75/100)*352 = 104
        expect(divs[0].style.top).toBe('104px')
    })

    it('uses theme.backgroundColor for the label border (dark-mode safe)', () => {
        const series: Series[] = [{ key: 's', label: 'S', color: '#f00', data: [50] }]
        const darkTheme: ChartTheme = { colors: ['#f00'], backgroundColor: '#222222' }
        const ctx = makeContext(series, { labels: ['Mon'], theme: darkTheme })
        const { container } = renderInChart(ctx, <ValueLabels />)
        const divs = labelDivs(container)
        expect(divs).toHaveLength(1)
        expect(divs[0].style.borderColor).toBe('#222222')
    })
})
