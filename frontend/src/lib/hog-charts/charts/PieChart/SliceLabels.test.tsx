import { cleanup, render, type RenderResult } from '@testing-library/react'
import React from 'react'

import { RadialLayoutContext } from '../../core/radial-context'
import type { RadialLayoutContextValue } from '../../core/radial-context'
import type { ResolvedSeries } from '../../core/types'
import { computePieLayout } from './computePieLayout'
import type { PieLayout } from './computePieLayout'
import { SliceLabels } from './SliceLabels'

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
})
