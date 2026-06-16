import { cleanup, type RenderResult } from '@testing-library/react'
import React from 'react'

import type { BaseChartContext } from '../core/chart-context'
import { makeOverlayContext, renderOverlayInChart } from '../testing'
import { AnomalyPointsLayer, type AnomalyMarker } from './AnomalyPointsLayer'

const DIMENSIONS = {
    width: 800,
    height: 400,
    plotLeft: 48,
    plotTop: 16,
    plotWidth: 720,
    plotHeight: 352,
}

// Simple linear y-scale: 0 -> plotBottom (368), 100 -> plotTop (16).
const yScale = (v: number): number => 368 - (v / 100) * 352

const CONTEXT: BaseChartContext = makeOverlayContext(
    {
        x: (label: string) => (({ Mon: 100, Tue: 400, Wed: 700 }) as Record<string, number | undefined>)[label],
        y: yScale,
        yTicks: () => [0, 50, 100],
    },
    {
        dimensions: DIMENSIONS,
        labels: ['Mon', 'Tue', 'Wed'],
    }
)

function renderInChart(node: React.ReactNode, ctx: BaseChartContext = CONTEXT): RenderResult {
    return renderOverlayInChart(node, ctx)
}

function dots(container: HTMLElement): NodeListOf<HTMLDivElement> {
    return container.querySelectorAll<HTMLDivElement>('div[data-attr="hog-chart-anomaly-point"]')
}

function marker(overrides: Partial<AnomalyMarker> = {}): AnomalyMarker {
    return { dataIndex: 1, value: 50, color: '#ff0000', yAxisId: 'left', ...overrides }
}

describe('AnomalyPointsLayer', () => {
    afterEach(() => cleanup())

    it('renders null when there are no markers', () => {
        const { container } = renderInChart(<AnomalyPointsLayer markers={[]} />)
        expect(container.firstChild).toBeNull()
    })

    it('renders a dot at the pixel computed from the scales', () => {
        const { container } = renderInChart(<AnomalyPointsLayer markers={[marker({ dataIndex: 1, value: 50 })]} />)
        const dot = dots(container)[0]
        expect(dot).toBeTruthy()
        // xScale('Tue') = 400, yScale(50) = 192; default radius 3 → left/top offset by 3.
        expect(dot.style.left).toBe('397px')
        expect(dot.style.top).toBe('189px')
        expect(dot.style.width).toBe('6px')
        expect(dot.style.height).toBe('6px')
    })

    it('fills the dot with the marker color', () => {
        const { container } = renderInChart(<AnomalyPointsLayer markers={[marker({ color: 'rgb(1, 2, 3)' })]} />)
        expect(dots(container)[0].style.backgroundColor).toBe('rgb(1, 2, 3)')
    })

    it('honors a custom radius', () => {
        const { container } = renderInChart(<AnomalyPointsLayer markers={[marker({ value: 50 })]} radius={5} />)
        const dot = dots(container)[0]
        expect(dot.style.width).toBe('10px')
        expect(dot.style.height).toBe('10px')
        // left = xScale('Tue') 400 - radius 5 = 395
        expect(dot.style.left).toBe('395px')
    })

    it.each([
        // dataIndex 9 is out of the labels array → no x pixel.
        ['label unknown to the x-scale', marker({ dataIndex: 9 })],
        // value 500 → yScale(500) = 368 - 1760 = well above plotTop, out of bounds.
        ['y value outside the plot bounds', marker({ value: 500 })],
    ])('skips a marker with %s', (_label, m) => {
        const { container } = renderInChart(<AnomalyPointsLayer markers={[m]} />)
        expect(dots(container)).toHaveLength(0)
    })

    it('positions a marker against its own yAxes scale when yAxisId matches', () => {
        const rightScale = (v: number): number => 368 - (v / 1000) * 352
        const multiAxisContext: BaseChartContext = {
            ...CONTEXT,
            scales: {
                ...CONTEXT.scales,
                yAxes: {
                    left: { scale: yScale, ticks: () => [0, 50, 100], position: 'left' },
                    y1: { scale: rightScale, ticks: () => [0, 500, 1000], position: 'right' },
                },
            },
        }
        // value 500 is out of bounds on the left axis but lands mid-plot on the right axis.
        const { container } = renderInChart(
            <AnomalyPointsLayer markers={[marker({ value: 500, yAxisId: 'y1' })]} />,
            multiAxisContext
        )
        const dot = dots(container)[0]
        expect(dot).toBeTruthy()
        // rightScale(500) = 192; radius 3 → top = 189.
        expect(dot.style.top).toBe('189px')
    })

    it('renders every in-bounds marker and skips only the out-of-bounds ones', () => {
        const { container } = renderInChart(
            <AnomalyPointsLayer
                markers={[
                    marker({ dataIndex: 0, value: 25 }),
                    marker({ dataIndex: 2, value: 75 }),
                    marker({ dataIndex: 1, value: 9999 }), // out of bounds
                ]}
            />
        )
        expect(dots(container)).toHaveLength(2)
    })

    it('renders a stable data-attr on each dot', () => {
        const { container } = renderInChart(<AnomalyPointsLayer markers={[marker(), marker({ dataIndex: 2 })]} />)
        const rendered = dots(container)
        expect(rendered).toHaveLength(2)
        expect(Array.from(rendered).map((dot) => dot.getAttribute('data-attr'))).toEqual([
            'hog-chart-anomaly-point',
            'hog-chart-anomaly-point',
        ])
    })
})
