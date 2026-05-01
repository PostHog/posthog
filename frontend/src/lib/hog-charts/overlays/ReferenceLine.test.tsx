import { cleanup, render } from '@testing-library/react'
import React from 'react'

import type { BaseChartContext, ChartLayoutContextValue } from '../core/chart-context'
import { ChartHoverContext, ChartLayoutContext } from '../core/chart-context'
import type { ChartTheme } from '../core/types'
import { ReferenceLine, ReferenceLines } from './ReferenceLine'

const DIMENSIONS = {
    width: 800,
    height: 400,
    plotLeft: 48,
    plotTop: 16,
    plotWidth: 720,
    plotHeight: 352,
}

const THEME: ChartTheme = { colors: ['#000'], backgroundColor: '#ffffff' }

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
    theme: THEME,
    resolveValue: (s, i) => s.data[i] ?? 0,
    canvasBounds: () => null,
    hoverIndex: -1,
}

function toLayout(ctx: BaseChartContext): ChartLayoutContextValue {
    const { hoverIndex: _hoverIndex, ...layout } = ctx
    return layout
}

function renderInChart(node: React.ReactNode, ctx: BaseChartContext = CONTEXT): ReturnType<typeof render> {
    return render(
        <ChartLayoutContext.Provider value={toLayout(ctx)}>
            <ChartHoverContext.Provider value={{ hoverIndex: ctx.hoverIndex }}>{node}</ChartHoverContext.Provider>
        </ChartLayoutContext.Provider>
    )
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

        it('uses the matching yAxes scale when a yAxisId is specified', () => {
            // Primary (left) scale ranges 0-100; right axis 'y1' ranges 0-1000.
            // Rendering `value=500` on the left axis would fall outside bounds, but the
            // right axis maps it to the middle of the plot.
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
            const { container } = renderInChart(<ReferenceLine value={500} yAxisId="y1" />, multiAxisContext)
            const line = lineDiv(container, 'top')
            expect(line).not.toBeNull()
            // rightScale(500) = 192; width 2 → top = 191
            expect(line!.style.top).toBe('191px')
        })

        it('falls back to the primary y-scale when yAxisId is unknown or absent', () => {
            const { container } = renderInChart(<ReferenceLine value={50} yAxisId="missing" />)
            const line = lineDiv(container, 'top')
            // Unknown axis id → default scale → same pixel as the plain `value=50` case (191px).
            expect(line!.style.top).toBe('191px')
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

        // var() literals are deliberately not in this table: jsdom doesn't store CSS
        // custom properties and reads back as the empty string, so we can only assert
        // the no-crash path for var() — see the dedicated test below. Real browsers
        // resolve the variable natively.
        it.each([
            ['hex literal', '#ff8800'],
            ['rgb literal', 'rgb(10, 20, 30)'],
        ])('passes %s color through to inline styles without resolving', (_name, color) => {
            const { container } = renderInChart(<ReferenceLine value={50} style={{ color }} />)
            const line = lineDiv(container, 'top')!
            expect(line.style.borderTopColor).toBe(color)
        })

        it('renders a var(...) color without throwing (browser-resolved at runtime)', () => {
            const { container } = renderInChart(<ReferenceLine value={50} style={{ color: 'var(--danger)' }} />)
            const line = lineDiv(container, 'top')
            // We're asserting the component mounts and exposes the line — the actual color
            // resolution happens in the browser's CSSOM, which jsdom doesn't implement.
            expect(line).not.toBeNull()
        })

        it('uses style.fillColor when provided, falling back to color', () => {
            const { container } = renderInChart(
                <ReferenceLine
                    value={50}
                    fillSide="above"
                    style={{ color: '#111', fillColor: 'rgb(50, 60, 70)', fillOpacity: 0.3 }}
                />
            )
            const fill = container.querySelectorAll<HTMLDivElement>('div')[0]
            expect(fill.style.backgroundColor).toBe('rgb(50, 60, 70)')
            expect(fill.style.opacity).toBe('0.3')
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
