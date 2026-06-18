import { cleanup, screen } from '@testing-library/react'

import type { TooltipContext } from '../core/types'
import { makeOverlayContext, renderOverlayInChart } from '../testing'
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

    it.each([
        ['default (no formatter)', undefined, (19402).toLocaleString(), null as string | null],
        ['custom valueFormatter', (v: number) => `${v}ms`, '19402ms', (19402).toLocaleString()],
    ])('formats values with %s', (_, formatter, expected, absent) => {
        renderTooltip({ valueFormatter: formatter })
        screen.getByText(expected)
        if (absent) {
            expect(screen.queryByText(absent)).toBeNull()
        }
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
        expect(screen.getByText('12$')).toBeTruthy()
        expect(screen.getByText('34%')).toBeTruthy()
    })

    describe('total row', () => {
        const TWO_SERIES: TooltipContext['seriesData'] = [
            { series: { key: 'a', label: 'A', data: [] }, value: 10, color: '#000' },
            { series: { key: 'b', label: 'B', data: [] }, value: 25, color: '#111' },
        ]

        it('sums the visible series and labels the row', () => {
            renderTooltip({ showTotal: true }, TWO_SERIES)
            expect(screen.getByText('Total:')).toBeTruthy()
            expect(screen.getByText((35).toLocaleString())).toBeTruthy()
        })

        it('uses a custom label and total formatter', () => {
            renderTooltip({ showTotal: true, totalLabel: 'Sum', totalFormatter: (v) => `$${v}` }, TWO_SERIES)
            expect(screen.getByText('Sum:')).toBeTruthy()
            expect(screen.getByText('$35')).toBeTruthy()
        })

        it('falls back to the per-series formatter for the total when no totalFormatter is given', () => {
            renderTooltip({ showTotal: true, valueFormatter: (v) => `${v}ms` }, TWO_SERIES)
            expect(screen.getByText('35ms')).toBeTruthy()
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
            expect(screen.getByText((35).toLocaleString())).toBeTruthy()
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
})
