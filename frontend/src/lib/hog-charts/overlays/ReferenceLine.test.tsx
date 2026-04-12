import { cleanup, render } from '@testing-library/react'
import React from 'react'

import type { BaseChartContext } from '../core/chart-context'
import { ChartContext } from '../core/chart-context'
import { ReferenceLine, ReferenceLines } from './ReferenceLine'

const DIMENSIONS = {
    width: 800,
    height: 400,
    plotLeft: 48,
    plotTop: 16,
    plotWidth: 720,
    plotHeight: 352,
}

// Simple linear y-scale: 0 -> plotBottom (368), 100 -> plotTop (16)
const yScale = (v: number): number => 368 - (v / 100) * 352

const CONTEXT: BaseChartContext = {
    dimensions: DIMENSIONS,
    labels: ['Mon', 'Tue', 'Wed'],
    series: [],
    scales: {
        x: (label: string) => (({ Mon: 100, Tue: 400, Wed: 700 }) as Record<string, number | undefined>)[label],
        y: yScale,
        yTicks: () => [0, 50, 100],
    },
    hoverIndex: -1,
}

function renderInChart(node: React.ReactNode): ReturnType<typeof render> {
    return render(<ChartContext.Provider value={CONTEXT}>{node}</ChartContext.Provider>)
}

function lineDiv(container: HTMLElement, side: 'top' | 'left'): HTMLDivElement | null {
    return container.querySelector<HTMLDivElement>(`div[style*="border-${side}"]`)
}

describe('ReferenceLine', () => {
    afterEach(() => cleanup())

    describe('horizontal', () => {
        it('renders null when value is not a number', () => {
            const { container } = renderInChart(<ReferenceLine value="Mon" />)
            expect(container.firstChild).toBeNull()
        })

        it('renders null when value is outside the plot bounds', () => {
            const { container } = renderInChart(<ReferenceLine value={-50} />)
            expect(container.firstChild).toBeNull()
        })

        it('renders the line at the y pixel computed from the scale', () => {
            const { container } = renderInChart(<ReferenceLine value={50} />)
            const line = lineDiv(container, 'top')
            expect(line).not.toBeNull()
            // y-scale(50) = 192; default stroke width 2 => top = 192 - 1 = 191
            expect(line!.style.top).toBe('191px')
            expect(line!.style.left).toBe('48px')
            expect(line!.style.width).toBe('720px')
        })

        it('renders the label text when provided', () => {
            const { getByText } = renderInChart(<ReferenceLine value={50} label="Target" />)
            expect(getByText('Target')).toBeTruthy()
        })

        it('anchors the label at the start when labelPosition="start"', () => {
            const { getByText } = renderInChart(<ReferenceLine value={50} label="T" labelPosition="start" />)
            const label = getByText('T') as HTMLDivElement
            expect(label.style.left).toBe('52px') // plotLeft + LABEL_PADDING
            expect(label.style.right).toBe('')
        })

        it('anchors the label at the end by default', () => {
            const { getByText } = renderInChart(<ReferenceLine value={50} label="T" />)
            const label = getByText('T') as HTMLDivElement
            expect(label.style.right).not.toBe('')
            expect(label.style.left).toBe('')
        })

        it('renders a fill rect above the line when fillSide="above"', () => {
            const { container } = renderInChart(<ReferenceLine value={50} fillSide="above" />)
            const divs = container.querySelectorAll<HTMLDivElement>('div')
            expect(divs).toHaveLength(2)
            const fill = divs[0]
            // above fill runs from plotTop down to the line y
            expect(fill.style.top).toBe('16px')
            expect(parseFloat(fill.style.height)).toBeGreaterThan(0)
        })

        it('renders a fill rect below the line when fillSide="below"', () => {
            const { container } = renderInChart(<ReferenceLine value={50} fillSide="below" />)
            const divs = container.querySelectorAll<HTMLDivElement>('div')
            expect(divs).toHaveLength(2)
            const fill = divs[0]
            expect(parseFloat(fill.style.top)).toBeGreaterThan(DIMENSIONS.plotTop)
        })
    })

    describe('vertical', () => {
        it('renders null when value is not a string', () => {
            const { container } = renderInChart(<ReferenceLine value={50} orientation="vertical" />)
            expect(container.firstChild).toBeNull()
        })

        it('renders null when label is unknown to the x-scale', () => {
            const { container } = renderInChart(<ReferenceLine value="Missing" orientation="vertical" />)
            expect(container.firstChild).toBeNull()
        })

        it('renders the line at the x pixel computed from the scale', () => {
            const { container } = renderInChart(<ReferenceLine value="Tue" orientation="vertical" />)
            const line = lineDiv(container, 'left')
            expect(line).not.toBeNull()
            // xScale('Tue') = 400; stroke width 2 => left = 400 - 1 = 399
            expect(line!.style.left).toBe('399px')
            expect(line!.style.top).toBe('16px')
            expect(line!.style.height).toBe('352px')
        })

        it('renders a fill rect to the left when fillSide="left"', () => {
            const { container } = renderInChart(<ReferenceLine value="Tue" orientation="vertical" fillSide="left" />)
            const fill = container.querySelectorAll<HTMLDivElement>('div')[0]
            expect(fill.style.left).toBe('48px')
            expect(fill.style.width).toBe('352px') // 400 - 48
        })

        it('renders a fill rect to the right when fillSide="right"', () => {
            const { container } = renderInChart(<ReferenceLine value="Tue" orientation="vertical" fillSide="right" />)
            const fill = container.querySelectorAll<HTMLDivElement>('div')[0]
            expect(fill.style.left).toBe('400px')
            expect(parseFloat(fill.style.width)).toBeGreaterThan(0)
        })
    })

    describe('variants and style overrides', () => {
        it.each([
            ['goal (default)', undefined, 'dashed', '2px'],
            ['alert', 'alert' as const, 'dashed', '2px'],
            ['marker', 'marker' as const, 'solid', '1px'],
        ])('variant %s renders expected stroke style', (_name, variant, expectedStyle, expectedWidth) => {
            const { container } = renderInChart(<ReferenceLine value={50} variant={variant} />)
            const line = lineDiv(container, 'top')!
            expect(line.style.borderTopStyle).toBe(expectedStyle)
            expect(line.style.borderTopWidth).toBe(expectedWidth)
        })

        it('applies an explicit style.stroke override', () => {
            const { container } = renderInChart(<ReferenceLine value={50} style={{ stroke: 'solid' }} />)
            const line = lineDiv(container, 'top')!
            expect(line.style.borderTopStyle).toBe('solid')
        })

        it('applies an explicit style.width override', () => {
            const { container } = renderInChart(<ReferenceLine value={50} style={{ width: 4 }} />)
            const line = lineDiv(container, 'top')!
            expect(line.style.borderTopWidth).toBe('4px')
        })
    })

    describe('ReferenceLines wrapper', () => {
        it('renders each props entry as its own line', () => {
            const { getByText } = renderInChart(
                <ReferenceLines
                    lines={[
                        { value: 25, label: 'Low' },
                        { value: 75, label: 'High' },
                    ]}
                />
            )
            expect(getByText('Low')).toBeTruthy()
            expect(getByText('High')).toBeTruthy()
        })

        it('omits lines whose value is out of plot bounds', () => {
            const { queryByText } = renderInChart(
                <ReferenceLines
                    lines={[
                        { value: 50, label: 'Visible' },
                        { value: -9999, label: 'Hidden' },
                    ]}
                />
            )
            expect(queryByText('Visible')).toBeTruthy()
            expect(queryByText('Hidden')).toBeNull()
        })
    })
})
