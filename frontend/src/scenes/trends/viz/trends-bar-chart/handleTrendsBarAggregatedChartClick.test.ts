import { NodeKind } from '~/queries/schema/schema-general'
import { EntityTypes } from '~/types'

import type { IndexedTrendResult } from '../../types'
import type { TrendsChartClickDeps } from '../handleTrendsChartClick'
import { handleTrendsBarAggregatedChartClick } from './handleTrendsBarAggregatedChartClick'

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

function makeDeps(overrides: Partial<TrendsChartClickDeps> = {}): TrendsChartClickDeps {
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
        indexedResults: [makeTrendResult()],
        openPersonsModal: jest.fn(),
        ...overrides,
    }
}

describe('handleTrendsBarAggregatedChartClick', () => {
    it('opens the persons modal for the result at the clicked dataIndex', () => {
        const openPersonsModal = jest.fn()
        const results = [
            makeTrendResult({ id: 1, label: 'Alpha' }),
            makeTrendResult({ id: 2, label: 'Beta' }),
            makeTrendResult({ id: 3, label: 'Gamma' }),
        ]
        const deps = makeDeps({ openPersonsModal, indexedResults: results })

        handleTrendsBarAggregatedChartClick(1, deps)

        expect(openPersonsModal).toHaveBeenCalledTimes(1)
        const call = openPersonsModal.mock.calls[0][0]
        expect(call.title).toBe('Beta')
        expect(call.query).toMatchObject({
            kind: NodeKind.InsightActorsQuery,
            series: 0,
            includeRecordings: true,
        })
        // No DateDisplay / day on aggregated — the actors query has no `day`.
        expect(call.query.day).toBeUndefined()
    })

    it.each([
        [0, { breakdown: 'A' }],
        [1, { breakdown: 'B' }],
        [2, { breakdown: 'C' }],
    ])("context.onDataPointClick at dataIndex %i carries that band's breakdown_value", (dataIndex, expected) => {
        const onDataPointClick = jest.fn()
        const results = [
            makeTrendResult({ id: 1, breakdown_value: 'A' }),
            makeTrendResult({ id: 2, breakdown_value: 'B' }),
            makeTrendResult({ id: 3, breakdown_value: 'C' }),
        ]
        const deps = makeDeps({ indexedResults: results, context: { onDataPointClick } })

        handleTrendsBarAggregatedChartClick(dataIndex, deps)

        expect(onDataPointClick).toHaveBeenCalledTimes(1)
        const [seriesArg] = onDataPointClick.mock.calls[0]
        expect(seriesArg).toMatchObject(expected)
        expect(seriesArg.day).toBeUndefined()
    })

    it('no-ops when dataIndex is out of bounds', () => {
        const openPersonsModal = jest.fn()
        const onDataPointClick = jest.fn()
        const results = [makeTrendResult({ id: 1 })]
        const deps = makeDeps({ openPersonsModal, indexedResults: results, context: { onDataPointClick } })

        handleTrendsBarAggregatedChartClick(5, deps)

        expect(openPersonsModal).not.toHaveBeenCalled()
        expect(onDataPointClick).not.toHaveBeenCalled()
    })

    it('does nothing when hasPersonsModal is false and no context callback', () => {
        const openPersonsModal = jest.fn()
        const results = [makeTrendResult({ id: 1 })]
        const deps = makeDeps({ openPersonsModal, hasPersonsModal: false, indexedResults: results })

        handleTrendsBarAggregatedChartClick(0, deps)

        expect(openPersonsModal).not.toHaveBeenCalled()
    })
})
