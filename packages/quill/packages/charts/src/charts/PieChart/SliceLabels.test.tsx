import { cleanup, render, type RenderResult } from '@testing-library/react'
import React from 'react'

import { RadialLayoutContext } from '../../core/radial-context'
import type { RadialLayoutContextValue } from '../../core/radial-context'
import type { ResolvedSeries } from '../../core/types'
import { computePieLayout } from './computePieLayout'
import type { PieLayout } from './computePieLayout'
import { nonCollidingKeys, SliceLabels } from './SliceLabels'
import type { LabelBox } from './SliceLabels'

const PLOT = { plotLeft: 0, plotTop: 0, plotWidth: 400, plotHeight: 400 }

function s(key: string, value: number, extras: Partial<ResolvedSeries> = {}): ResolvedSeries {
    return { key, label: key.toUpperCase(), data: [value], color: '#000', ...extras }
}

function renderWithLayout(layout: PieLayout, node: React.ReactNode): RenderResult {
    const value: RadialLayoutContextValue = { layout, canvasBounds: () => null }
    return render(<RadialLayoutContext.Provider value={value}>{node}</RadialLayoutContext.Provider>)
}

function labels(container: HTMLElement): HTMLDivElement[] {
    return Array.from(container.querySelectorAll<HTMLDivElement>('[data-attr="hog-chart-pie-slice-label"]'))
}

describe('SliceLabels', () => {
    afterEach(() => cleanup())

    it('renders one label per slice when all are above the threshold', () => {
        const layout = computePieLayout({
            series: [s('a', 25), s('b', 25), s('c', 25), s('d', 25)],
            dimensions: PLOT,
        })
        const { container } = renderWithLayout(layout, <SliceLabels />)
        expect(labels(container)).toHaveLength(4)
    })

    it('hides slices below minSlicePercentForLabel', () => {
        const layout = computePieLayout({
            series: [s('a', 96), s('b', 2), s('c', 2)],
            dimensions: PLOT,
        })
        const { container } = renderWithLayout(layout, <SliceLabels minSlicePercentForLabel={0.05} />)
        // only the 96-value slice is >= 5%
        expect(labels(container)).toHaveLength(1)
    })

    it('pushes labels further from the center as labelRadiusRatio increases', () => {
        const layout = computePieLayout({ series: [s('a', 50), s('b', 50)], dimensions: PLOT })
        const cx = layout.cx
        const { container: near } = renderWithLayout(layout, <SliceLabels labelRadiusRatio={0.3} />)
        const nearOffset = Math.abs(parseFloat(labels(near)[0].style.left) - cx)
        const { container: far } = renderWithLayout(layout, <SliceLabels labelRadiusRatio={0.9} />)
        const farOffset = Math.abs(parseFloat(labels(far)[0].style.left) - cx)
        expect(farOffset).toBeGreaterThan(nearOffset)
    })

    it('respects visibility.valueLabel = false', () => {
        const layout = computePieLayout({
            series: [s('a', 25), s('b', 25, { visibility: { valueLabel: false } }), s('c', 25), s('d', 25)],
            dimensions: PLOT,
        })
        const { container } = renderWithLayout(layout, <SliceLabels />)
        expect(labels(container)).toHaveLength(3)
        expect(labels(container).map((d) => d.textContent)).not.toContain(expect.stringContaining('B'))
    })

    it('renders nothing when both value and label are disabled', () => {
        const layout = computePieLayout({
            series: [s('a', 25), s('b', 25)],
            dimensions: PLOT,
        })
        const { container } = renderWithLayout(
            layout,
            <SliceLabels showValueOnSlice={false} showLabelOnSlice={false} />
        )
        expect(labels(container)).toHaveLength(0)
    })

    it('uses the provided formatter for values', () => {
        const layout = computePieLayout({
            series: [s('a', 1500)],
            dimensions: PLOT,
        })
        const { container } = renderWithLayout(
            layout,
            <SliceLabels valueFormatter={(v) => `$${(v / 1000).toFixed(1)}k`} />
        )
        expect(labels(container)[0].textContent).toContain('$1.5k')
    })

    it('renders percent strings when isPercent is true', () => {
        const layout = computePieLayout({
            series: [s('a', 25), s('b', 75)],
            dimensions: PLOT,
        })
        const { container } = renderWithLayout(layout, <SliceLabels isPercent />)
        const text = labels(container)
            .map((d) => d.textContent ?? '')
            .join('|')
        expect(text).toContain('25%')
        expect(text).toContain('75%')
    })

    it('shows the breakdown label above the value when showLabelOnSlice is true', () => {
        const layout = computePieLayout({
            series: [s('a', 50), s('b', 50)],
            dimensions: PLOT,
        })
        const { container } = renderWithLayout(layout, <SliceLabels showLabelOnSlice showValueOnSlice />)
        const a = labels(container)[0]
        expect(a.textContent).toContain('A')
        expect(a.textContent).toContain('50')
    })

    // y=0 for every box, so overlap is decided purely by x against the summed half-widths.
    function box(key: string, x: number, value: number, halfWidth = 10): LabelBox {
        return { key, x, y: 0, halfWidth, halfHeight: 10, value, lines: [key] }
    }

    it('keeps every label when none of the boxes overlap', () => {
        const kept = nonCollidingKeys([box('a', 0, 1), box('b', 100, 1), box('c', 200, 1)])
        expect([...kept].sort()).toEqual(['a', 'b', 'c'])
    })

    it('drops the smaller-value label when two boxes overlap', () => {
        // 5px apart, half-widths 10 each → boxes overlap; b carries the larger value.
        const kept = nonCollidingKeys([box('a', 0, 3), box('b', 5, 9)])
        expect(kept.has('b')).toBe(true)
        expect(kept.has('a')).toBe(false)
    })

    it('keeps only the largest label in a crowded cluster', () => {
        const kept = nonCollidingKeys([box('a', 0, 1), box('b', 4, 5), box('c', 8, 3)])
        expect([...kept]).toEqual(['b'])
    })
})
