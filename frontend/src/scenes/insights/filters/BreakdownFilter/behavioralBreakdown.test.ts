import { InsightQueryNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import {
    BehavioralEventType,
    BehavioralPropertyFilter,
    ChartDisplayType,
    PropertyFilterType,
    PropertyOperator,
    TimeUnitType,
} from '~/types'

import { canAddBehavioralBreakdown, createBehavioralBreakdownSeries } from './behavioralBreakdown'

const behavioralFilter: BehavioralPropertyFilter = {
    type: PropertyFilterType.Behavioral,
    value: BehavioralEventType.PerformEvent,
    key: 'signed_up',
    event_type: 'events' as const,
    time_value: 30,
    time_interval: TimeUnitType.Day,
}

const query: TrendsQuery = {
    kind: NodeKind.TrendsQuery,
    series: [
        {
            kind: NodeKind.EventsNode,
            event: 'uploaded_file',
            properties: [
                {
                    type: PropertyFilterType.Event,
                    key: 'file_type',
                    value: 'csv',
                    operator: PropertyOperator.Exact,
                },
            ],
        },
    ],
}

describe('behavioralBreakdown', () => {
    it('creates complementary performed and did not perform series without dropping existing filters', () => {
        const existingProperties = query.series[0].properties ?? []

        expect(createBehavioralBreakdownSeries(query.series[0], behavioralFilter)).toEqual([
            {
                ...query.series[0],
                custom_name: 'Performed',
                properties: [...existingProperties, behavioralFilter],
            },
            {
                ...query.series[0],
                custom_name: 'Did not perform',
                properties: [...existingProperties, { ...behavioralFilter, negation: true }],
            },
        ])
    })

    it.each<[string, InsightQueryNode, boolean]>([
        ['the feature is disabled', query, false],
        ['a breakdown already exists', { ...query, breakdownFilter: { breakdown: '$browser' } }, true],
        ['there are multiple series', { ...query, series: [...query.series, ...query.series] }, true],
        ['formula mode is active', { ...query, trendsFilter: { formula: 'A' } }, true],
        [
            'the display only supports one series',
            { ...query, trendsFilter: { display: ChartDisplayType.BoldNumber } },
            true,
        ],
        [
            'the series comes from the data warehouse',
            {
                ...query,
                series: [
                    {
                        kind: NodeKind.DataWarehouseNode,
                        id: 'orders',
                        table_name: 'orders',
                        id_field: 'id',
                        timestamp_field: 'created_at',
                        distinct_id_field: 'user_id',
                    },
                ],
            },
            true,
        ],
    ])('does not offer a behavioral breakdown when %s', (_name, candidate, featureEnabled) => {
        expect(canAddBehavioralBreakdown(candidate, featureEnabled)).toBe(false)
    })

    it('offers a behavioral breakdown for a single event series', () => {
        expect(canAddBehavioralBreakdown(query, true)).toBe(true)
    })
})
