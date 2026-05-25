import { cleanup, render } from '@testing-library/react'

import { ChartLayoutContext, type ChartLayoutContextValue } from '../../core/chart-context'
import type { ChartTheme, Series, TooltipContext } from '../../core/types'
import { mockRect } from '../../testing'
import { BoxPlotTooltip } from './BoxPlotTooltip'
import type { BoxPlotDatum } from './computeBoxLayout'

const THEME: ChartTheme = {
    colors: ['#1f77b4'],
    backgroundColor: '#ffffff',
    tooltipBackground: '#000',
    tooltipColor: '#fff',
}

interface AdaptedMeta {
    datums: (BoxPlotDatum | null)[]
}

function datum(overrides: Partial<BoxPlotDatum> = {}): BoxPlotDatum {
    return { min: 1, p25: 2, median: 3, mean: 4, p75: 5, max: 6, ...overrides }
}

function makeContext(
    seriesEntries: { key: string; label: string; color: string; datums: (BoxPlotDatum | null)[] }[],
    dataIndex: number,
    label: string
): TooltipContext<AdaptedMeta> {
    // `data`/`value` on the inner adapter Series are never read by BoxPlotTooltip — the
    // tooltip reads from `meta.datums` directly. Falling back to 0 here lets the null-datum
    // test (which intentionally passes a null entry) construct a context without throwing.
    return {
        dataIndex,
        label,
        seriesData: seriesEntries.map((s) => {
            const series: Series<AdaptedMeta> = {
                key: s.key,
                label: s.label,
                color: s.color,
                data: s.datums.map((d) => d?.median ?? 0),
                meta: { datums: s.datums },
            }
            return { series, value: s.datums[dataIndex]?.median ?? 0, color: s.color }
        }),
        position: { x: 0, y: 0 },
        hoverPosition: { x: 0, y: 0 },
        canvasBounds: mockRect,
        isPinned: false,
    }
}

function layoutValue(): ChartLayoutContextValue {
    return {
        scales: { x: () => 0, y: () => 0, yTicks: () => [] },
        dimensions: { width: 200, height: 100, plotLeft: 0, plotTop: 0, plotWidth: 200, plotHeight: 100 },
        labels: [],
        series: [],
        theme: THEME,
        resolvePositionValue: (s, i) => s.data[i] as number,
        canvasBounds: () => mockRect,
        axis: { orientation: 'vertical', xTickFormatter: undefined, isPercent: false },
    }
}

function renderWithLayout(node: React.ReactElement): ReturnType<typeof render> {
    return render(<ChartLayoutContext.Provider value={layoutValue()}>{node}</ChartLayoutContext.Provider>)
}

describe('BoxPlotTooltip', () => {
    afterEach(cleanup)

    it('renders the six stats in the canonical order (Max → p75 → Median → Mean → p25 → Min)', () => {
        const ctx = makeContext(
            [
                {
                    key: 'a',
                    label: 'A',
                    color: '#111',
                    datums: [datum({ min: 1, p25: 2, median: 3, mean: 4, p75: 5, max: 6 })],
                },
            ],
            0,
            'Mon'
        )
        const { container } = renderWithLayout(<BoxPlotTooltip ctx={ctx} grouped={false} />)
        const labels = Array.from(container.querySelectorAll('tr')).map((tr) =>
            (tr.firstElementChild as HTMLElement).textContent!.trim()
        )
        expect(labels).toEqual(['Max', '75th percentile', 'Median', 'Mean', '25th percentile', 'Min'])
    })

    it('renders the values in the canonical row order', () => {
        const ctx = makeContext(
            [
                {
                    key: 'a',
                    label: 'A',
                    color: '#111',
                    datums: [datum({ min: 1, p25: 2, median: 3, mean: 4, p75: 5, max: 6 })],
                },
            ],
            0,
            'Mon'
        )
        const { container } = renderWithLayout(<BoxPlotTooltip ctx={ctx} grouped={false} />)
        const values = Array.from(container.querySelectorAll('tr')).map((tr) =>
            (tr.lastElementChild as HTMLElement).textContent!.trim()
        )
        expect(values).toEqual(['6', '5', '3', '4', '2', '1'])
    })

    it('shows the x label in the header', () => {
        const ctx = makeContext([{ key: 'a', label: 'A', color: '#111', datums: [datum()] }], 0, 'Mon')
        const { container } = renderWithLayout(<BoxPlotTooltip ctx={ctx} grouped={false} />)
        expect(container.textContent).toContain('Mon')
    })

    it('renders one stat group per visible series (multi-series grouped)', () => {
        const ctx = makeContext(
            [
                { key: 'a', label: 'A', color: '#111', datums: [datum({ median: 10 })] },
                { key: 'b', label: 'B', color: '#222', datums: [datum({ median: 20 })] },
            ],
            0,
            'Mon'
        )
        const { container } = renderWithLayout(<BoxPlotTooltip ctx={ctx} grouped={true} />)
        // Per-series headers should be visible when grouped.
        expect(container.textContent).toContain('A')
        expect(container.textContent).toContain('B')
        // Two stat tables, one per series.
        expect(container.querySelectorAll('table')).toHaveLength(2)
    })

    it('hides per-series labels when not grouped (single series)', () => {
        const ctx = makeContext([{ key: 'a', label: 'A-label', color: '#111', datums: [datum()] }], 0, 'Mon')
        const { container } = renderWithLayout(<BoxPlotTooltip ctx={ctx} grouped={false} />)
        // No per-series header — series label is not rendered as a heading in single-series mode.
        const headers = Array.from(container.querySelectorAll('.font-semibold')).map((el) => el.textContent)
        // The single "Mon" date header is the only font-semibold heading.
        expect(headers).toContain('Mon')
        expect(headers).not.toContain('A-label')
    })

    it('returns null when no datum is present at the index', () => {
        const ctx = makeContext([{ key: 'a', label: 'A', color: '#111', datums: [null] }], 0, 'Mon')
        const { container } = renderWithLayout(<BoxPlotTooltip ctx={ctx} grouped={false} />)
        expect(container.firstChild).toBeNull()
    })

    it('passes through to a user-supplied tooltip when provided', () => {
        const userTooltip = jest.fn((): React.ReactElement => <div data-attr="custom-boxplot-user-tooltip">custom</div>)
        const ctx = makeContext([{ key: 'a', label: 'A', color: '#111', datums: [datum()] }], 0, 'Mon')
        const { container } = renderWithLayout(<BoxPlotTooltip ctx={ctx} grouped={false} userTooltip={userTooltip} />)
        expect(container.querySelector('[data-attr="custom-boxplot-user-tooltip"]')).not.toBeNull()
        expect(userTooltip).toHaveBeenCalled()
    })
})
