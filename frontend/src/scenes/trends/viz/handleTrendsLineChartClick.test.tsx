import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'

import type { IndexedTrendResult } from '../types'
import { handleTrendsLineChartClick, type TrendsLineChartClickDeps } from './handleTrendsLineChartClick'

function makeTrendResult(overrides: Partial<IndexedTrendResult> = {}): IndexedTrendResult {
    return {
        id: 0,
        seriesIndex: 0,
        colorIndex: 0,
        action: {
            id: '$pageview',
            type: 'events',
            order: 0,
            name: '$pageview',
            days: ['2024-06-10', '2024-06-11', '2024-06-12'],
        },
        label: '$pageview',
        count: 10,
        data: [1, 2, 3],
        labels: ['Mon', 'Tue', 'Wed'],
        days: ['2024-06-10', '2024-06-11', '2024-06-12'],
        filter: {},
        ...overrides,
    } as IndexedTrendResult
}

function keyFor(trendResult: IndexedTrendResult): string {
    return `${trendResult.id}`
}

function makeDeps(overrides: Partial<TrendsLineChartClickDeps> = {}): TrendsLineChartClickDeps {
    const trendResult = makeTrendResult()
    return {
        hasPersonsModal: true,
        interval: 'day',
        timezone: 'UTC',
        weekStartDay: 0,
        resolvedDateRange: null,
        querySource: {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        } as TrendsQuery,
        indexedResults: [trendResult],
        openPersonsModal: jest.fn(),
        ...overrides,
    }
}

describe('handleTrendsLineChartClick', () => {
    it('opens the persons modal with the correct actors query for a basic click', () => {
        const openPersonsModal = jest.fn()
        const trendResult = makeTrendResult()
        const deps = makeDeps({ openPersonsModal, indexedResults: [trendResult] })

        handleTrendsLineChartClick(keyFor(trendResult), 1, deps)

        expect(openPersonsModal).toHaveBeenCalledTimes(1)
        const call = openPersonsModal.mock.calls[0][0]
        expect(call.query).toMatchObject({
            kind: NodeKind.InsightActorsQuery,
            day: '2024-06-11',
            series: 0,
            includeRecordings: true,
        })
        expect(call.additionalSelect).toEqual({
            value_at_data_point: 'event_count',
            matched_recordings: 'matched_recordings',
        })
        expect(call.orderBy).toEqual(['event_count DESC, actor_id DESC'])
    })

    it('passes breakdown_value through to the actors query', () => {
        const openPersonsModal = jest.fn()
        const trendResult = makeTrendResult({ breakdown_value: 'Spike' })
        const deps = makeDeps({ openPersonsModal, indexedResults: [trendResult] })

        handleTrendsLineChartClick(keyFor(trendResult), 2, deps)

        expect(openPersonsModal.mock.calls[0][0].query).toMatchObject({
            day: '2024-06-12',
            breakdown: 'Spike',
        })
    })

    it('passes compare_label through to the actors query', () => {
        const openPersonsModal = jest.fn()
        const trendResult = makeTrendResult({ compare_label: 'previous' as any })
        const deps = makeDeps({ openPersonsModal, indexedResults: [trendResult] })

        handleTrendsLineChartClick(keyFor(trendResult), 0, deps)

        expect(openPersonsModal.mock.calls[0][0].query).toMatchObject({
            day: '2024-06-10',
            compare: 'previous',
        })
    })

    it('calls context.onDataPointClick instead of opening the modal when provided', () => {
        const openPersonsModal = jest.fn()
        const onDataPointClick = jest.fn()
        const trendResult = makeTrendResult({ breakdown_value: 'Spike' })
        const referenceResult = makeTrendResult({ id: 99 })
        const deps = makeDeps({
            openPersonsModal,
            indexedResults: [referenceResult, trendResult],
            context: { onDataPointClick } as any,
        })

        handleTrendsLineChartClick(keyFor(trendResult), 1, deps)

        expect(openPersonsModal).not.toHaveBeenCalled()
        expect(onDataPointClick).toHaveBeenCalledTimes(1)
        expect(onDataPointClick).toHaveBeenCalledWith(expect.objectContaining({ day: '2024-06-11' }), referenceResult)
    })

    it('does nothing when hasPersonsModal is false and no context callback', () => {
        const openPersonsModal = jest.fn()
        const trendResult = makeTrendResult()
        const deps = makeDeps({ openPersonsModal, hasPersonsModal: false, indexedResults: [trendResult] })

        handleTrendsLineChartClick(keyFor(trendResult), 1, deps)

        expect(openPersonsModal).not.toHaveBeenCalled()
    })

    it('still fires context.onDataPointClick when hasPersonsModal is false', () => {
        const openPersonsModal = jest.fn()
        const onDataPointClick = jest.fn()
        const trendResult = makeTrendResult()
        const deps = makeDeps({
            openPersonsModal,
            hasPersonsModal: false,
            indexedResults: [trendResult],
            context: { onDataPointClick } as any,
        })

        handleTrendsLineChartClick(keyFor(trendResult), 1, deps)

        expect(onDataPointClick).toHaveBeenCalledTimes(1)
        expect(openPersonsModal).not.toHaveBeenCalled()
    })

    it('no-ops when the clicked series has no matching indexedResult', () => {
        const openPersonsModal = jest.fn()
        const onDataPointClick = jest.fn()
        const trendResult = makeTrendResult({ id: 42 })
        const deps = makeDeps({
            openPersonsModal,
            indexedResults: [trendResult],
            context: { onDataPointClick } as any,
        })

        expect(() => handleTrendsLineChartClick('999', 1, deps)).not.toThrow()
        expect(openPersonsModal).not.toHaveBeenCalled()
        expect(onDataPointClick).not.toHaveBeenCalled()
    })

    it('uses trendResult.days[index] as fallback when action.days is missing', () => {
        const openPersonsModal = jest.fn()
        const trendResult = makeTrendResult({
            action: undefined as any,
            days: ['D0', 'D1', 'D2'],
        })
        const deps = makeDeps({ openPersonsModal, indexedResults: [trendResult] })

        handleTrendsLineChartClick(keyFor(trendResult), 2, deps)

        expect(openPersonsModal.mock.calls[0][0].query).toMatchObject({ day: 'D2' })
    })

    it('does nothing when querySource is missing and no context callback', () => {
        const openPersonsModal = jest.fn()
        const trendResult = makeTrendResult()
        const deps = makeDeps({ openPersonsModal, querySource: null, indexedResults: [trendResult] })

        handleTrendsLineChartClick(keyFor(trendResult), 1, deps)

        expect(openPersonsModal).not.toHaveBeenCalled()
    })
})
