import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType, InsightModel } from '~/types'

import { cropInsightToZoom } from './zoomPreview'

const DAYS = ['2026-10-01', '2026-10-02', '2026-10-03', '2026-10-04', '2026-10-05']

function trendsInsight(result: Record<string, unknown>[], trendsFilter: Record<string, unknown> = {}): InsightModel {
    return {
        query: {
            kind: NodeKind.InsightVizNode,
            source: { kind: NodeKind.TrendsQuery, series: [], trendsFilter },
        },
        result,
    } as unknown as InsightModel
}

describe('cropInsightToZoom', () => {
    it.each([
        {
            name: 'keeps only the buckets in the range',
            insight: trendsInsight([
                { days: DAYS, labels: DAYS, data: [1, 2, 3, 4, 5], breakdown_value: ['a', 'b', 'c', 'd', 'e'] },
            ]),
            range: { dateFrom: '2026-10-02', dateTo: '2026-10-03' },
            expected: [
                {
                    days: ['2026-10-02', '2026-10-03'],
                    data: [2, 3],
                    count: 5,
                    breakdown_value: ['a', 'b', 'c', 'd', 'e'],
                },
            ],
        },
        {
            name: 'keeps a coarser bucket that only partly overlaps the range',
            insight: trendsInsight([{ days: ['2026-09-27', '2026-10-04', '2026-10-11'], data: [7, 8, 9] }]),
            range: { dateFrom: '2026-10-06', dateTo: '2026-10-12' },
            expected: [{ days: ['2026-10-04', '2026-10-11'], data: [8, 9] }],
        },
    ])('$name', ({ insight, range, expected }) => {
        expect(cropInsightToZoom(insight, range).result).toMatchObject(expected)
    })

    it.each([
        {
            name: 'a total over the range',
            insight: trendsInsight([{ days: DAYS, data: [1, 2, 3, 4, 5] }], { display: ChartDisplayType.BoldNumber }),
        },
        {
            name: 'a moving average',
            insight: trendsInsight([{ days: DAYS, data: [1, 2, 3, 4, 5] }], { smoothingIntervals: 7 }),
        },
        {
            name: 'a cumulative line',
            insight: trendsInsight([{ days: DAYS, data: [1, 3, 6, 10, 15] }], {
                display: ChartDisplayType.ActionsLineGraphCumulative,
            }),
        },
        {
            name: 'a comparison with the previous period',
            insight: trendsInsight([
                { days: DAYS, data: [1, 2, 3, 4, 5], compare_label: 'current' },
                { days: DAYS, data: [9, 8, 7, 6, 5], compare_label: 'previous' },
            ]),
        },
    ])('leaves $name uncropped', ({ insight }) => {
        expect(cropInsightToZoom(insight, { dateFrom: '2026-10-02', dateTo: '2026-10-03' })).toBe(insight)
    })

    it('leaves results that end before the range uncropped', () => {
        const insight = trendsInsight([{ days: DAYS, data: [1, 2, 3, 4, 5] }])
        expect(cropInsightToZoom(insight, { dateFrom: '2026-10-10', dateTo: '2026-10-12' })).toBe(insight)
    })
})
