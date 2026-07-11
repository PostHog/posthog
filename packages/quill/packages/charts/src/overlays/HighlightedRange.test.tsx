import { cleanup } from '@testing-library/react'
import React from 'react'

import type { BaseChartContext } from '../core/chart-context'
import type { ChartScales } from '../core/types'
import { makeOverlayContext, renderOverlayInChart } from '../testing'
import { HighlightedRange } from './HighlightedRange'

const DIMENSIONS = {
    width: 800,
    height: 400,
    plotLeft: 48,
    plotTop: 16,
    plotWidth: 720,
    plotHeight: 352,
}

const LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
const X_POSITIONS: Record<string, number> = { Mon: 100, Tue: 250, Wed: 400, Thu: 550, Fri: 700 }
const BAND_WIDTH = 100

function makeContext(scales: Partial<ChartScales> = {}): BaseChartContext {
    return makeOverlayContext(
        {
            x: (label: string) => X_POSITIONS[label],
            y: (v: number) => v,
            yTicks: () => [],
            extent: () => BAND_WIDTH,
            ...scales,
        },
        { dimensions: DIMENSIONS, labels: LABELS }
    )
}

function fillBox(container: HTMLElement): HTMLDivElement | null {
    return container.querySelector<HTMLDivElement>('[data-attr="hog-chart-highlighted-range"]')
}

describe('HighlightedRange', () => {
    afterEach(() => cleanup())

    it('covers the full bands of both endpoints on a band (bar) chart', () => {
        const { container } = renderOverlayInChart(<HighlightedRange start="Tue" end="Thu" />, makeContext())
        const box = fillBox(container)!
        // Tue center 250 - half band 50 = 200; Thu center 550 + 50 = 600.
        expect(box.style.left).toBe('200px')
        expect(box.style.width).toBe('400px')
        expect(box.style.top).toBe('16px')
        expect(box.style.height).toBe('352px')
    })

    it('runs point-to-point when the chart has no band extent (line chart)', () => {
        const { container } = renderOverlayInChart(
            <HighlightedRange start="Tue" end="Thu" />,
            makeContext({ extent: undefined })
        )
        const box = fillBox(container)!
        expect(box.style.left).toBe('250px')
        expect(box.style.width).toBe('300px')
    })

    it('resolves numeric endpoints as data indices into the labels array', () => {
        const { container } = renderOverlayInChart(<HighlightedRange start={1} end={3} />, makeContext())
        expect(fillBox(container)!.style.left).toBe('200px')
        expect(fillBox(container)!.style.width).toBe('400px')
    })

    it('normalizes reversed endpoints', () => {
        const { container } = renderOverlayInChart(<HighlightedRange start="Thu" end="Tue" />, makeContext())
        expect(fillBox(container)!.style.left).toBe('200px')
        expect(fillBox(container)!.style.width).toBe('400px')
    })

    it('clamps the box to the plot area when the range spills past its edges', () => {
        // Edge bands centered at 60 and 740 spill outside the plot ([48, 768]) once
        // expanded by half a 100px band: lo = 10, hi = 790.
        const { container } = renderOverlayInChart(
            <HighlightedRange start="Mon" end="Fri" />,
            makeContext({ x: (label: string) => ({ ...X_POSITIONS, Mon: 60, Fri: 740 })[label] })
        )
        const box = fillBox(container)!
        expect(box.style.left).toBe('48px')
        expect(box.style.width).toBe('720px')
    })

    it.each([
        ['unknown label', { start: 'Nope', end: 'Thu' }],
        ['out-of-range index', { start: 1, end: 99 }],
    ])('renders null for an endpoint that does not resolve (%s)', (_name, props) => {
        const { container } = renderOverlayInChart(<HighlightedRange {...props} />, makeContext())
        expect(container.firstChild).toBeNull()
    })

    it('renders the border box by default and omits it at borderOpacity=0', () => {
        const withBorder = renderOverlayInChart(<HighlightedRange start="Tue" end="Thu" />, makeContext())
        const borderDiv = withBorder.container.querySelectorAll('div')[1] as HTMLDivElement
        expect(borderDiv.style.borderWidth).toBe('1px')
        expect(borderDiv.style.borderColor).toBe('#8f8f8f')
        cleanup()
        const noBorder = renderOverlayInChart(
            <HighlightedRange start="Tue" end="Thu" borderOpacity={0} />,
            makeContext()
        )
        expect(noBorder.container.querySelectorAll('div')[1]).toBeUndefined()
    })
})
