import { cleanup, screen } from '@testing-library/react'

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

function renderTooltip(props: TooltipProps = {}, seriesData: TooltipContext['seriesData'] = SERIES_DATA): void {
    const ctx: TooltipContext = {
        dataIndex: 0,
        label: 'When',
        seriesData,
        position: { x: 0, y: 0 },
        hoverPosition: null,
        canvasBounds: CANVAS_BOUNDS,
        isPinned: false,
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
            screen.getByText('Total:')
            screen.getByText((35).toLocaleString())
        })

        it('uses a custom label and total formatter', () => {
            renderTooltip({ showTotal: true, totalLabel: 'Sum', totalFormatter: (v) => `$${v}` }, TWO_SERIES)
            screen.getByText('Sum:')
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
            expect(screen.queryByText('Total:')).toBeNull()
        })

        it('is suppressed when showTotal is not set', () => {
            renderTooltip({}, TWO_SERIES)
            expect(screen.queryByText('Total:')).toBeNull()
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
            expect(screen.queryByText('Total:')).toBeNull()
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
    })
})
