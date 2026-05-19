import type { TooltipContext } from 'lib/hog-charts'

import type { TrendsSeriesMeta } from './trendsSeriesMeta'
import { resolveTooltipDate } from './TrendsTooltip'

function makeContext(overrides: Partial<TooltipContext<TrendsSeriesMeta>> = {}): TooltipContext<TrendsSeriesMeta> {
    return {
        dataIndex: 0,
        label: '',
        seriesData: [],
        position: { x: 0, y: 0 },
        hoverPosition: null,
        canvasBounds: {} as DOMRect,
        isPinned: false,
        ...overrides,
    }
}

function makeSeriesEntry(
    days: string[] | undefined,
    overrides: Partial<TooltipContext<TrendsSeriesMeta>['seriesData'][number]> = {}
): TooltipContext<TrendsSeriesMeta>['seriesData'][number] {
    return {
        series: {
            key: 'series',
            label: 'Series',
            data: [],
            meta: days === undefined ? {} : { days },
        },
        value: 0,
        color: '#000',
        ...overrides,
    }
}

describe('resolveTooltipDate', () => {
    it('returns the days entry for the primary series at the hovered index', () => {
        const context = makeContext({
            dataIndex: 1,
            label: '2-Mar-2024',
            seriesData: [makeSeriesEntry(['2024-03-01', '2024-03-02', '2024-03-03'])],
        })
        expect(resolveTooltipDate(context)).toEqual('2024-03-02')
    })

    // Regression: derived overlays (CI bands / moving averages / trend lines) can land first
    // in seriesData when the primary feed lacks a days array; the header used to fall through
    // to undefined and render as "undefined (UTC)".
    it('falls back to a later series that carries days when the first one does not', () => {
        const context = makeContext({
            dataIndex: 2,
            label: '3-Mar-2024',
            seriesData: [makeSeriesEntry(undefined), makeSeriesEntry(['2024-03-01', '2024-03-02', '2024-03-03'])],
        })
        expect(resolveTooltipDate(context)).toEqual('2024-03-03')
    })

    it('falls back to the chart-level x-axis label when no series carry days', () => {
        const context = makeContext({
            dataIndex: 0,
            label: '2024-04-28',
            seriesData: [makeSeriesEntry(undefined), makeSeriesEntry(undefined)],
        })
        expect(resolveTooltipDate(context)).toEqual('2024-04-28')
    })

    it('falls back to the x-axis label when the picked series has a days array but no value at this index', () => {
        const context = makeContext({
            dataIndex: 5,
            label: '5-Mar-2024',
            seriesData: [makeSeriesEntry(['2024-03-01', '2024-03-02'])],
        })
        expect(resolveTooltipDate(context)).toEqual('5-Mar-2024')
    })
})
