import { NodeKind } from '~/queries/schema/schema-general'
import { CompareLabelType, EntityTypes } from '~/types'

import type { IndexedTrendResult } from '../../types'
import { handleTrendsLineChartClick, type TrendsLineChartClickDeps } from './handleTrendsLineChartClick'

function makeTrendResult(overrides: Partial<IndexedTrendResult> = {}): IndexedTrendResult {
    return {
        id: 0,
        seriesIndex: 0,
        colorIndex: 0,
        action: {
            id: '$pageview',
            type: EntityTypes.EVENTS,
            order: 0,
            name: '$pageview',
            days: ['2024-06-10', '2024-06-11', '2024-06-12'],
        },
        label: '$pageview',
        count: 10,
        aggregated_value: 10,
        data: [1, 2, 3],
        labels: ['Mon', 'Tue', 'Wed'],
        days: ['2024-06-10', '2024-06-11', '2024-06-12'],
        ...overrides,
    }
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
        },
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

    it.each([
        ['breakdown_value', { breakdown_value: 'Spike' }, 2, { day: '2024-06-12', breakdown: 'Spike' }],
        ['compare_label', { compare_label: CompareLabelType.Previous }, 0, { day: '2024-06-10', compare: 'previous' }],
    ])('passes %s through to the actors query', (_field, override, dataIndex, expected) => {
        const openPersonsModal = jest.fn()
        const trendResult = makeTrendResult(override)
        const deps = makeDeps({ openPersonsModal, indexedResults: [trendResult] })

        handleTrendsLineChartClick(keyFor(trendResult), dataIndex, deps)

        expect(openPersonsModal.mock.calls[0][0].query).toMatchObject(expected)
    })

    it.each([
        ['breakdown_value', { breakdown_value: 'Spike' }, 1, { day: '2024-06-11', breakdown: 'Spike' }],
        ['compare_label', { compare_label: CompareLabelType.Previous }, 0, { day: '2024-06-10', compare: 'previous' }],
    ])(
        'forwards %s to context.onDataPointClick instead of opening the modal',
        (_field, override, dataIndex, expected) => {
            const openPersonsModal = jest.fn()
            const onDataPointClick = jest.fn()
            const trendResult = makeTrendResult(override)
            const deps = makeDeps({
                openPersonsModal,
                indexedResults: [trendResult],
                context: { onDataPointClick },
            })

            handleTrendsLineChartClick(keyFor(trendResult), dataIndex, deps)

            expect(openPersonsModal).not.toHaveBeenCalled()
            expect(onDataPointClick).toHaveBeenCalledTimes(1)
            expect(onDataPointClick).toHaveBeenCalledWith(expect.objectContaining(expected), expect.anything())
        }
    )

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
            context: { onDataPointClick },
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
            context: { onDataPointClick },
        })

        expect(() => handleTrendsLineChartClick('999', 1, deps)).not.toThrow()
        expect(openPersonsModal).not.toHaveBeenCalled()
        expect(onDataPointClick).not.toHaveBeenCalled()
    })

    it('uses trendResult.days[index] as fallback when action.days is missing', () => {
        const openPersonsModal = jest.fn()
        const trendResult = makeTrendResult({
            // ActionFilter without a `days` array — the adapter should fall
            // back to reading from the top-level trend result `days`.
            action: { id: '$pageview', type: EntityTypes.EVENTS, order: 0, name: '$pageview' },
            days: ['D0', 'D1', 'D2'],
        })
        const deps = makeDeps({ openPersonsModal, indexedResults: [trendResult] })

        handleTrendsLineChartClick(keyFor(trendResult), 2, deps)

        expect(openPersonsModal.mock.calls[0][0].query).toMatchObject({ day: 'D2' })
    })

    it('no-ops when neither action.days nor trendResult.days can supply a day', () => {
        const openPersonsModal = jest.fn()
        const onDataPointClick = jest.fn()
        const trendResult = makeTrendResult({
            action: { id: '$pageview', type: EntityTypes.EVENTS, order: 0, name: '$pageview' },
            days: [],
        })
        const deps = makeDeps({
            openPersonsModal,
            indexedResults: [trendResult],
            context: { onDataPointClick },
        })

        handleTrendsLineChartClick(keyFor(trendResult), 2, deps)

        expect(openPersonsModal).not.toHaveBeenCalled()
        expect(onDataPointClick).not.toHaveBeenCalled()
    })

    it('does nothing when querySource is missing and no context callback', () => {
        const openPersonsModal = jest.fn()
        const trendResult = makeTrendResult()
        const deps = makeDeps({ openPersonsModal, querySource: null, indexedResults: [trendResult] })

        handleTrendsLineChartClick(keyFor(trendResult), 1, deps)

        expect(openPersonsModal).not.toHaveBeenCalled()
    })
})
