import { cleanup, fireEvent, screen } from '@testing-library/react'

import type { TooltipContext } from '../core/types'
import { createDefaultTooltipAccessor, makeOverlayContext, renderOverlayInChart } from '../testing'
import { DefaultTooltip } from './DefaultTooltip'

const SCALES = { x: () => 0, y: (v: number) => v, yTicks: () => [] }

const SERIES_DATA: TooltipContext['seriesData'] = [
    { series: { key: 'a', label: 'A', data: [] }, value: 19402, color: '#000' },
]
const CANVAS_BOUNDS = {
    x: 0,
    y: 0,
    width: 800,
    height: 400,
    top: 0,
    right: 800,
    bottom: 400,
    left: 0,
    toJSON: () => ({}),
} as DOMRect

type TooltipProps = Omit<Parameters<typeof DefaultTooltip>[0], keyof TooltipContext>

function renderTooltip(
    props: TooltipProps = {},
    seriesData: TooltipContext['seriesData'] = SERIES_DATA,
    ctxOverrides: Partial<TooltipContext> = {}
): void {
    const ctx: TooltipContext = {
        dataIndex: 0,
        label: 'When',
        seriesData,
        position: { x: 0, y: 0 },
        hoverPosition: null,
        canvasBounds: CANVAS_BOUNDS,
        isPinned: false,
        ...ctxOverrides,
    }
    renderOverlayInChart(<DefaultTooltip {...ctx} {...props} />, makeOverlayContext(SCALES))
}

describe('DefaultTooltip', () => {
    afterEach(cleanup)

    it('formats values with default (no formatter)', () => {
        renderTooltip({})
        screen.getByText((19402).toLocaleString())
    })

    it('formats values with custom valueFormatter', () => {
        renderTooltip({ valueFormatter: (v: number) => `${v}ms` })
        screen.getByText('19402ms')
        expect(screen.queryByText((19402).toLocaleString())).toBeNull()
    })

    it('passes each row entry to valueFormatter so it can format per-series', () => {
        const seriesData: TooltipContext['seriesData'] = [
            { series: { key: 'usd', label: 'Revenue', data: [], meta: { unit: '$' } }, value: 12, color: '#000' },
            { series: { key: 'pct', label: 'Rate', data: [], meta: { unit: '%' } }, value: 34, color: '#111' },
        ]
        renderTooltip(
            {
                valueFormatter: (value, entry) => `${value}${(entry.series.meta as { unit: string }).unit}`,
            },
            seriesData
        )
        screen.getByText('12$')
        screen.getByText('34%')
    })

    describe('total row', () => {
        const TWO_SERIES: TooltipContext['seriesData'] = [
            { series: { key: 'a', label: 'A', data: [] }, value: 10, color: '#000' },
            { series: { key: 'b', label: 'B', data: [] }, value: 25, color: '#111' },
        ]

        it('sums the visible series and labels the row', () => {
            renderTooltip({ showTotal: true }, TWO_SERIES)
            screen.getByText('Total')
            screen.getByText((35).toLocaleString())
        })

        it('uses a custom label and total formatter', () => {
            renderTooltip({ showTotal: true, totalLabel: 'Sum', totalFormatter: (v) => `$${v}` }, TWO_SERIES)
            screen.getByText('Sum')
            screen.getByText('$35')
        })

        it('falls back to valueFormatter for the total, applied with the first summable entry', () => {
            const metaSeries: TooltipContext['seriesData'] = [
                { series: { key: 'usd', label: 'Revenue', data: [], meta: { unit: '$' } }, value: 10, color: '#000' },
                {
                    series: { key: 'usd2', label: 'Revenue 2', data: [], meta: { unit: '€' } },
                    value: 25,
                    color: '#111',
                },
            ]
            renderTooltip(
                {
                    showTotal: true,
                    valueFormatter: (v, entry) => `${v}${(entry.series.meta as { unit: string }).unit}`,
                },
                metaSeries
            )
            // total uses summable[0]'s entry (unit '$'), not summable[1]'s ('€')
            screen.getByText('35$')
            expect(screen.queryByText('35€')).toBeNull()
        })

        it('is suppressed for a single series', () => {
            renderTooltip({ showTotal: true }, SERIES_DATA)
            expect(screen.queryByText('Total')).toBeNull()
        })

        it('is suppressed when showTotal is not set', () => {
            renderTooltip({}, TWO_SERIES)
            expect(screen.queryByText('Total')).toBeNull()
        })

        it('excludes overlay series from the sum and the summable count', () => {
            const withOverlay: TooltipContext['seriesData'] = [
                ...TWO_SERIES,
                { series: { key: 'goal', label: 'Goal', data: [], overlay: true }, value: 1000, color: '#222' },
            ]
            renderTooltip({ showTotal: true }, withOverlay)
            screen.getByText((35).toLocaleString())
            expect(screen.queryByText((1035).toLocaleString())).toBeNull()
        })

        it('is suppressed when only one non-overlay series remains', () => {
            const oneRealOneOverlay: TooltipContext['seriesData'] = [
                { series: { key: 'a', label: 'A', data: [] }, value: 10, color: '#000' },
                { series: { key: 'goal', label: 'Goal', data: [], overlay: true }, value: 30, color: '#222' },
            ]
            renderTooltip({ showTotal: true }, oneRealOneOverlay)
            expect(screen.queryByText('Total')).toBeNull()
        })
    })

    describe('createDefaultTooltipAccessor', () => {
        it('reads the label, rows, values, swatch colors, and total', () => {
            const seriesData: TooltipContext['seriesData'] = [
                { series: { key: 'a', label: 'Revenue', data: [] }, value: 100, color: 'rgb(255, 0, 0)' },
                { series: { key: 'b', label: 'Cost', data: [] }, value: 40, color: 'rgb(0, 255, 0)' },
            ]
            renderTooltip({ showTotal: true, valueFormatter: (v) => `$${v}` }, seriesData)

            const tooltip = createDefaultTooltipAccessor(document.body)
            expect(tooltip.label()).toBe('When')
            expect(tooltip.rows()).toEqual(['Revenue', 'Cost'])
            expect(tooltip.value('Revenue')).toBe('$100')
            expect(tooltip.value('Cost')).toBe('$40')
            expect(tooltip.swatchColors()).toEqual(['rgb(255, 0, 0)', 'rgb(0, 255, 0)'])
            expect(tooltip.total()).toBe('$140')
        })

        it('returns undefined total when no total row is shown', () => {
            renderTooltip({})
            expect(createDefaultTooltipAccessor(document.body).total()).toBeUndefined()
        })

        it('includes overlay series in rows (rows is every rendered row, not summable-only)', () => {
            const seriesData: TooltipContext['seriesData'] = [
                { series: { key: 'a', label: 'Visits', data: [] }, value: 100, color: 'rgb(1, 2, 3)' },
                { series: { key: 'goal', label: 'Goal', data: [], overlay: true }, value: 30, color: 'rgb(4, 5, 6)' },
            ]
            renderTooltip({}, seriesData)
            expect(createDefaultTooltipAccessor(document.body).rows()).toEqual(['Visits', 'Goal'])
        })
    })

    describe('row presentation props', () => {
        const TWO_SERIES: TooltipContext['seriesData'] = [
            { series: { key: 'a', label: 'Alpha', data: [] }, value: 10, color: '#000' },
            { series: { key: 'b', label: 'Beta', data: [] }, value: 25, color: '#111' },
        ]

        it('renders the header label by default', () => {
            renderTooltip({})
            expect(document.querySelector('[data-attr="hog-chart-tooltip-label"]')?.textContent).toBe('When')
        })

        it('hides the header label when showHeader is false', () => {
            renderTooltip({ showHeader: false })
            expect(document.querySelector('[data-attr="hog-chart-tooltip-label"]')).toBeNull()
        })

        it('labelRenderer overrides each row label', () => {
            renderTooltip({ labelRenderer: (entry) => `# ${entry.series.label}` }, TWO_SERIES)
            expect(createDefaultTooltipAccessor(document.body).rows()).toEqual(['# Alpha', '# Beta'])
        })

        it('hideZeroRows drops rows whose value is exactly 0', () => {
            const withZero: TooltipContext['seriesData'] = [
                { series: { key: 'a', label: 'Alpha', data: [] }, value: 0, color: '#000' },
                { series: { key: 'b', label: 'Beta', data: [] }, value: 25, color: '#111' },
            ]
            renderTooltip({ hideZeroRows: true }, withZero)
            expect(createDefaultTooltipAccessor(document.body).rows()).toEqual(['Beta'])
        })

        it('keeps zero-value rows when hideZeroRows is not set', () => {
            const withZero: TooltipContext['seriesData'] = [
                { series: { key: 'a', label: 'Alpha', data: [] }, value: 0, color: '#000' },
                { series: { key: 'b', label: 'Beta', data: [] }, value: 25, color: '#111' },
            ]
            renderTooltip({}, withZero)
            expect(createDefaultTooltipAccessor(document.body).rows()).toEqual(['Alpha', 'Beta'])
        })

        it('onRowClick fires with the clicked row entry', () => {
            const onRowClick = jest.fn()
            renderTooltip({ onRowClick }, TWO_SERIES)
            const rows = document.querySelectorAll<HTMLElement>('[data-attr="hog-chart-tooltip-row"]')
            fireEvent.click(rows[1])
            expect(onRowClick).toHaveBeenCalledTimes(1)
            expect(onRowClick.mock.calls[0][0].series.key).toBe('b')
        })

        it('sorts rows by yPixel ascending (visual top-to-bottom) when not sortedByValue', () => {
            const withYPixel: TooltipContext['seriesData'] = [
                { series: { key: 'low', label: 'Low', data: [] }, value: 5, color: '#000', yPixel: 300 },
                { series: { key: 'high', label: 'High', data: [] }, value: 5, color: '#111', yPixel: 50 },
            ]
            renderTooltip({}, withYPixel)
            // yPixel 50 sits visually higher on the canvas, so it leads despite being declared second.
            expect(createDefaultTooltipAccessor(document.body).rows()).toEqual(['High', 'Low'])
        })

        it('marks the row whose yPixel is closest to the cursor with data-closest', () => {
            const withYPixel: TooltipContext['seriesData'] = [
                { series: { key: 'a', label: 'Alpha', data: [] }, value: 5, color: '#000', yPixel: 40 },
                { series: { key: 'b', label: 'Beta', data: [] }, value: 5, color: '#111', yPixel: 300 },
            ]
            renderTooltip({}, withYPixel, { hoverPosition: { x: 0, y: 290 } })
            const closest = document.querySelectorAll<HTMLElement>('[data-closest="true"]')
            expect(closest).toHaveLength(1)
            expect(closest[0].querySelector('[data-attr="hog-chart-tooltip-series"]')?.textContent).toBe('Beta')
        })
    })
})
