import { cleanup, type RenderResult } from '@testing-library/react'
import React from 'react'

import type { BaseChartContext } from '../core/chart-context'
import type { ChartScales, ChartTheme, ResolvedSeries, ResolveValueFn } from '../core/types'
import { makeOverlayContext, type OverlayContextOverrides, renderOverlayInChart } from '../testing'
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

function makeContext(
    series: ResolvedSeries[],
    overrides: OverlayContextOverrides & { scales?: ChartScales } = {}
): BaseChartContext {
    const { scales, ...rest } = overrides
    return makeOverlayContext(scales ?? { x: xScale, y: yScale, yTicks: () => [0, 50, 100] }, {
        dimensions: DIMENSIONS,
        labels: LABELS,
        series,
        ...rest,
    })
}

function renderInChart(context: BaseChartContext, node: React.ReactNode): RenderResult {
    return renderOverlayInChart(node, context)
}

function labelDivs(container: HTMLElement): HTMLDivElement[] {
    return Array.from(container.querySelectorAll<HTMLDivElement>('[data-attr="hog-chart-value-label"]'))
}

describe('ValueLabels', () => {
    afterEach(() => cleanup())

    it('renders one label per non-zero data point in a single series', () => {
        const series: ResolvedSeries[] = [{ key: 's', label: 'S', color: '#f00', data: [10, 20, 30, 40, 50] }]
        const { container } = renderInChart(makeContext(series), <ValueLabels />)
        const divs = labelDivs(container)
        expect(divs).toHaveLength(5)
        expect(divs.map((d) => d.textContent)).toEqual(['10', '20', '30', '40', '50'])
    })

    it.each<[string, ((value: number) => string) | undefined, number[], string[]]>([
        ['no formatter → toLocaleString', undefined, [1234, 5678], [(1234).toLocaleString(), (5678).toLocaleString()]],
        ['custom formatter', (v) => `$${(v / 1000).toFixed(1)}k`, [1000, 2000], ['$1.0k', '$2.0k']],
    ])('formats labels: %s', (_name, formatter, data, expected) => {
        const series: ResolvedSeries[] = [{ key: 's', label: 'S', color: '#f00', data }]
        const ctx = makeContext(series, { labels: ['Mon', 'Tue'] })
        const { container } = renderInChart(ctx, <ValueLabels valueFormatter={formatter} />)
        const divs = labelDivs(container)
        expect(divs.map((d) => d.textContent)).toEqual(expected)
    })

    it('skips zero values', () => {
        const series: ResolvedSeries[] = [{ key: 's', label: 'S', color: '#f00', data: [10, 0, 30, 0, 50] }]
        const { container } = renderInChart(makeContext(series), <ValueLabels />)
        expect(labelDivs(container).map((d) => d.textContent)).toEqual(['10', '30', '50'])
    })

    it('skips non-finite values (NaN, Infinity)', () => {
        const series: ResolvedSeries[] = [{ key: 's', label: 'S', color: '#f00', data: [10, NaN, 30, Infinity, 50] }]
        const { container } = renderInChart(makeContext(series), <ValueLabels />)
        expect(labelDivs(container).map((d) => d.textContent)).toEqual(['10', '30', '50'])
    })

    it('skips series where visibility.excluded is true', () => {
        const series: ResolvedSeries[] = [
            { key: 'a', label: 'A', color: '#f00', data: [10, 20, 30, 40, 50] },
            { key: 'b', label: 'B', color: '#0f0', data: [60, 70, 80, 90, 100], visibility: { excluded: true } },
        ]
        const { container } = renderInChart(makeContext(series), <ValueLabels />)
        const divs = labelDivs(container)
        expect(divs).toHaveLength(5)
        divs.forEach((d) => expect(d.style.backgroundColor).toBe('rgb(255, 0, 0)'))
    })

    it('positions negative values below the point and positive values above', () => {
        const series: ResolvedSeries[] = [{ key: 's', label: 'S', color: '#f00', data: [50, -50, 25, -25, 75] }]
        const { container } = renderInChart(makeContext(series), <ValueLabels />)
        const divs = labelDivs(container)
        expect(divs).toHaveLength(5)
        // positive values (50, 25, 75) render above → transform translates up by full height
        // negative values (-50, -25) render below → transform is plain translateX
        const values = [50, -50, 25, -25, 75]
        divs.forEach((d, i) => {
            const value = values[i]
            if (value >= 0) {
                expect(d.style.transform).toBe('translate(-50%, -100%)')
            } else {
                expect(d.style.transform).toBe('translateX(-50%)')
            }
        })
    })

    it('drops overlapping labels via greedy collision avoidance', () => {
        // Two points at the same x: only one should survive.
        const series: ResolvedSeries[] = [{ key: 's', label: 'S', color: '#f00', data: [50, 50] }]
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
        const series: ResolvedSeries[] = [{ key: 'right', label: 'R', color: '#00f', data: [500], yAxisId: 'y1' }]
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
        const series: ResolvedSeries[] = [{ key: 's', label: 'S', color: '#f00', data: [50], yAxisId: 'missing' }]
        const ctx = makeContext(series, { labels: ['Mon'] })
        const { container } = renderInChart(ctx, <ValueLabels />)
        const divs = labelDivs(container)
        expect(divs).toHaveLength(1)
        // yScale(50) = 192
        expect(divs[0].style.top).toBe('192px')
    })

    it('renders one label per series at the same x, each with its own color', () => {
        const series: ResolvedSeries[] = [
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
        const series: ResolvedSeries[] = [{ key: 's', label: 'S', color: '#f00', data: [NaN, NaN, NaN] }]
        const ctx = makeContext(series, { labels: ['Mon', 'Tue', 'Wed'] })
        const { container } = renderInChart(ctx, <ValueLabels />)
        expect(labelDivs(container)).toHaveLength(0)
    })

    it('positions labels at the resolved (e.g. stacked) y, not the raw series.data y', () => {
        // Raw value 25 sits at y=278 on the left axis; stacking lifts it to top-of-stack=75 → y=104.
        // The resolveValue closure mimics what LineChart provides for stacked series.
        const series: ResolvedSeries[] = [{ key: 's', label: 'S', color: '#f00', data: [25] }]
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
        const series: ResolvedSeries[] = [{ key: 's', label: 'S', color: '#f00', data: [50] }]
        const darkTheme: ChartTheme = { colors: ['#f00'], backgroundColor: '#222222' }
        const ctx = makeContext(series, { labels: ['Mon'], theme: darkTheme })
        const { container } = renderInChart(ctx, <ValueLabels />)
        const divs = labelDivs(container)
        expect(divs).toHaveLength(1)
        expect(divs[0].style.borderColor).toBe('#222222')
    })

    it.each<[string, number, string, string]>([
        ['positive value past the right edge', 50, '192px', 'translateY(-50%)'],
        ['negative value past the left edge', -50, '544px', 'translate(-100%, -50%)'],
    ])('horizontal: places %s', (_name, value, expectedLeft, expectedTransform) => {
        const series: ResolvedSeries[] = [{ key: 's', label: 'S', color: '#f00', data: [value] }]
        const ctx = makeContext(series, {
            axisOrientation: 'horizontal',
            labels: ['Mon'],
            scales: { x: () => 60, y: yScale, yTicks: () => [0, 50, 100] },
        })
        const divs = labelDivs(renderInChart(ctx, <ValueLabels />).container)
        expect(divs[0].style.left).toBe(expectedLeft)
        expect(divs[0].style.transform).toBe(expectedTransform)
    })

    it('horizontal: drops vertically overlapping labels via per-series collision avoidance', () => {
        const series: ResolvedSeries[] = [{ key: 's', label: 'S', color: '#f00', data: [40, 60] }]
        const ctx = makeContext(series, {
            axisOrientation: 'horizontal',
            labels: ['A', 'B'],
            scales: { x: () => 200, y: yScale, yTicks: () => [0, 50, 100] },
        })
        expect(labelDivs(renderInChart(ctx, <ValueLabels />).container)).toHaveLength(1)
    })

    describe('stack-total mode', () => {
        it('skips mixed-sign bands (no single visual stack apex)', () => {
            const series: ResolvedSeries[] = [
                { key: 'a', label: 'A', color: '#a00', data: [30, 30] },
                { key: 'b', label: 'B', color: '#0a0', data: [-10, 5] },
            ]
            const ctx = makeContext(series, { labels: ['Mon', 'Tue'] })
            const divs = labelDivs(renderInChart(ctx, <ValueLabels mode="stack-total" />).container)
            // Mon is mixed-sign (skipped); Tue is all-positive total=35.
            expect(divs.map((d) => d.textContent)).toEqual(['35'])
        })

        it('sums visible series per band, skips zero totals and excluded series', () => {
            const series: ResolvedSeries[] = [
                { key: 'a', label: 'A', color: '#112233', data: [10, 0, 30] },
                { key: 'b', label: 'B', color: '#445566', data: [5, 0, 5] },
                { key: 'c', label: 'C', color: '#778899', data: [99, 99, 99], visibility: { valueLabel: false } },
            ]
            const ctx = makeContext(series, { labels: ['Mon', 'Tue', 'Wed'] })
            const divs = labelDivs(renderInChart(ctx, <ValueLabels mode="stack-total" />).container)
            expect(divs.map((d) => d.textContent)).toEqual(['15', '35'])
            // Total label uses the topmost visible series color.
            expect(divs[0].style.backgroundColor).toBe('rgb(68, 85, 102)')
        })
    })

    it('isPercent on context is informational — consumers supply their own formatter', () => {
        const series: ResolvedSeries[] = [{ key: 's', label: 'S', color: '#f00', data: [0.25, 0.5, 0.75] }]
        const ctx = makeContext(series, { isPercent: true, labels: ['Mon', 'Tue', 'Wed'] })
        const { container } = renderInChart(ctx, <ValueLabels valueFormatter={(v) => `${(v * 100).toFixed(1)}%`} />)
        expect(labelDivs(container).map((d) => d.textContent)).toEqual(['25.0%', '50.0%', '75.0%'])
    })
})
