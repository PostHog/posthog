import type { AnomalyPoint } from 'lib/components/Alerts/types'

import { EntityTypes } from '~/types'

import type { IndexedTrendResult } from '../../types'
import { buildAnomalyMarkers } from './anomalyPointsAdapter'

function makeResult(overrides: Partial<IndexedTrendResult> = {}): IndexedTrendResult {
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

const colorOf = (r: IndexedTrendResult): string => `#color${r.seriesIndex}`
const yAxisOf = (): string => 'left'
const notHidden = (): boolean => false

describe('buildAnomalyMarkers', () => {
    it('returns empty for nullish/empty input', () => {
        expect(buildAnomalyMarkers(null, [makeResult()], colorOf, yAxisOf, notHidden)).toEqual([])
        expect(buildAnomalyMarkers([], [makeResult()], colorOf, yAxisOf, notHidden)).toEqual([])
        expect(
            buildAnomalyMarkers(
                [{ index: 0, date: '2024-06-10', score: 0.9, seriesIndex: 0 }],
                [],
                colorOf,
                yAxisOf,
                notHidden
            )
        ).toEqual([])
    })

    it('maps a single anomaly to a marker at the resolved date index with the series color', () => {
        const anomalies: AnomalyPoint[] = [{ index: 0, date: '2024-06-11', score: 0.85, seriesIndex: 0 }]
        const markers = buildAnomalyMarkers(anomalies, [makeResult()], colorOf, yAxisOf, notHidden)
        expect(markers).toEqual([{ dataIndex: 1, value: 2, color: '#color0', score: 0.85, yAxisId: 'left' }])
    })

    it('maps anomaly seriesIndex to the matching IndexedTrendResult.seriesIndex (not array order)', () => {
        const results = [
            makeResult({ id: 0, seriesIndex: 5, data: [1, 1, 1] }),
            makeResult({ id: 1, seriesIndex: 2, data: [9, 9, 9] }),
        ]
        const anomalies: AnomalyPoint[] = [{ index: 0, date: '2024-06-12', score: null, seriesIndex: 2 }]
        const markers = buildAnomalyMarkers(anomalies, results, colorOf, yAxisOf, notHidden)
        expect(markers).toHaveLength(1)
        expect(markers[0]).toMatchObject({ value: 9, dataIndex: 2 })
    })

    it('drops anomalies for hidden series', () => {
        const anomalies: AnomalyPoint[] = [{ index: 0, date: '2024-06-10', score: 0.9, seriesIndex: 0 }]
        expect(buildAnomalyMarkers(anomalies, [makeResult()], colorOf, yAxisOf, () => true)).toEqual([])
    })

    it.each([
        ['date not in current period', '2099-01-01'],
        ['empty date string', ''],
    ])('drops anomalies whose %s', (_, date) => {
        const anomalies: AnomalyPoint[] = [{ index: 0, date, score: null, seriesIndex: 0 }]
        expect(buildAnomalyMarkers(anomalies, [makeResult()], colorOf, yAxisOf, notHidden)).toEqual([])
    })

    it('drops anomalies when the resolved value is non-finite', () => {
        const result = makeResult({ data: [1, NaN, 3] })
        const anomalies: AnomalyPoint[] = [{ index: 0, date: '2024-06-11', score: null, seriesIndex: 0 }]
        expect(buildAnomalyMarkers(anomalies, [result], colorOf, yAxisOf, notHidden)).toEqual([])
    })

    it('falls back to result.days when action.days is missing', () => {
        const result = makeResult({
            action: { id: '$pageview', type: EntityTypes.EVENTS, order: 0, name: '$pageview' },
            days: ['D0', 'D1', 'D2'],
        })
        const anomalies: AnomalyPoint[] = [{ index: 0, date: 'D2', score: 0.5, seriesIndex: 0 }]
        const markers = buildAnomalyMarkers(anomalies, [result], colorOf, yAxisOf, notHidden)
        expect(markers).toHaveLength(1)
        expect(markers[0]).toMatchObject({ dataIndex: 2, value: 3 })
    })

    it('uses the y-axis id supplied by the caller', () => {
        const anomalies: AnomalyPoint[] = [{ index: 0, date: '2024-06-10', score: null, seriesIndex: 0 }]
        const markers = buildAnomalyMarkers(anomalies, [makeResult()], colorOf, () => 'y2', notHidden)
        expect(markers[0].yAxisId).toBe('y2')
    })
})
