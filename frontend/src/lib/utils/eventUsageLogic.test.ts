import { NodeKind } from '~/queries/schema/schema-general'
import type {
    ExperimentFunnelMetric,
    ExperimentFunnelsQuery,
    ExperimentMeanMetric,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    ExperimentTrendsQuery,
} from '~/queries/schema/schema-general'
import { BaseMathType } from '~/types'

import { getEventPropertiesForMetric } from './eventUsageLogic'

describe('getEventPropertiesForMetric', () => {
    describe('ExperimentMetric (new format)', () => {
        it('extracts funnel metric properties', () => {
            const metric: ExperimentFunnelMetric = {
                kind: NodeKind.ExperimentMetric,
                metric_type: 'funnel' as const,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: 'pageview',
                        properties: [{ type: 'event', key: 'url', value: '/home' }],
                    },
                    { kind: NodeKind.ActionsNode, id: 1 },
                    {
                        kind: NodeKind.EventsNode,
                        event: 'purchase',
                        properties: [
                            { type: 'event', key: 'amount', value: '10' },
                            { type: 'event', key: 'currency', value: 'USD' },
                        ],
                    },
                ],
                funnel_order_type: 'strict',
            } as ExperimentFunnelMetric

            const result = getEventPropertiesForMetric(metric) as Record<string, any>

            expect(result.kind).toBe(NodeKind.ExperimentMetric)
            expect(result.metric_type).toBe('funnel')
            expect(result.has_breakdown).toBe(false)
            expect(result.funnel_steps_count).toBe(3)
            expect(result.funnel_order_type).toBe('strict')
            expect(result.property_filter_count).toBe(3)
        })

        it('extracts mean metric properties', () => {
            const metric: ExperimentMeanMetric = {
                kind: NodeKind.ExperimentMetric,
                metric_type: 'mean' as const,
                source: {
                    kind: NodeKind.EventsNode,
                    event: 'purchase',
                    math: BaseMathType.UniqueUsers,
                    properties: [{ type: 'event', key: 'amount', value: '10' }],
                },
            } as ExperimentMeanMetric

            const result = getEventPropertiesForMetric(metric) as Record<string, any>

            expect(result.kind).toBe(NodeKind.ExperimentMetric)
            expect(result.metric_type).toBe('mean')
            expect(result.source_kind).toBe(NodeKind.EventsNode)
            expect(result.is_data_warehouse).toBe(false)
            expect(result.property_filter_count).toBe(1)
            expect(result.math_type).toBe(BaseMathType.UniqueUsers)
            expect(result.has_math_hogql).toBe(false)
        })

        it('extracts mean metric with data warehouse source', () => {
            const metric: ExperimentMeanMetric = {
                kind: NodeKind.ExperimentMetric,
                metric_type: 'mean' as const,
                source: {
                    kind: NodeKind.ExperimentDataWarehouseNode,
                    table_name: 'my_table',
                    timestamp_field: 'ts',
                    events_join_key: 'id',
                    data_warehouse_join_key: 'event_id',
                },
            } as ExperimentMeanMetric

            const result = getEventPropertiesForMetric(metric) as Record<string, any>

            expect(result.is_data_warehouse).toBe(true)
            expect(result.source_kind).toBe(NodeKind.ExperimentDataWarehouseNode)
            expect(result.property_filter_count).toBe(0)
            expect(result.math_type).toBeUndefined()
            expect(result.has_math_hogql).toBe(false)
        })

        it('extracts ratio metric properties from both sources', () => {
            const metric: ExperimentRatioMetric = {
                kind: NodeKind.ExperimentMetric,
                metric_type: 'ratio' as const,
                numerator: {
                    kind: NodeKind.EventsNode,
                    event: 'purchase',
                    math: BaseMathType.TotalCount,
                    properties: [{ type: 'event', key: 'a', value: '1' }],
                },
                denominator: {
                    kind: NodeKind.EventsNode,
                    event: 'pageview',
                    math_hogql: 'count()',
                    properties: [
                        { type: 'event', key: 'b', value: '2' },
                        { type: 'event', key: 'c', value: '3' },
                    ],
                },
            } as ExperimentRatioMetric

            const result = getEventPropertiesForMetric(metric) as Record<string, any>

            expect(result.metric_type).toBe('ratio')
            expect(result.numerator_source_kind).toBe(NodeKind.EventsNode)
            expect(result.denominator_source_kind).toBe(NodeKind.EventsNode)
            expect(result.is_data_warehouse).toBe(false)
            expect(result.property_filter_count).toBe(3)
            expect(result.numerator_math_type).toBe(BaseMathType.TotalCount)
            expect(result.has_math_hogql).toBe(true)
        })

        it('extracts retention metric properties', () => {
            const metric: ExperimentRetentionMetric = {
                kind: NodeKind.ExperimentMetric,
                metric_type: 'retention' as const,
                start_event: { kind: NodeKind.EventsNode, event: 'signup' },
                completion_event: {
                    kind: NodeKind.EventsNode,
                    event: 'purchase',
                    properties: [{ type: 'event', key: 'x', value: '1' }],
                },
                retention_window_start: 1,
                retention_window_end: 8,
                retention_window_unit: 'day',
                start_handling: 'first_seen',
            } as ExperimentRetentionMetric

            const result = getEventPropertiesForMetric(metric) as Record<string, any>

            expect(result.metric_type).toBe('retention')
            expect(result.is_data_warehouse).toBe(false)
            expect(result.property_filter_count).toBe(1)
        })

        it.each([
            { unit: 'day', start: 1, end: 8, expected: 7 },
            { unit: 'week', start: 0, end: 2, expected: 14 },
            { unit: 'month', start: 0, end: 1, expected: 30 },
            { unit: 'hour', start: 0, end: 5, expected: undefined },
        ])('computes retention_window_days for $unit unit', ({ unit, start, end, expected }) => {
            const metric = {
                kind: NodeKind.ExperimentMetric,
                metric_type: 'retention' as const,
                start_event: { kind: NodeKind.EventsNode, event: 'signup' },
                completion_event: { kind: NodeKind.EventsNode, event: 'purchase' },
                retention_window_start: start,
                retention_window_end: end,
                retention_window_unit: unit,
                start_handling: 'first_seen',
            } as ExperimentRetentionMetric

            const result = getEventPropertiesForMetric(metric) as Record<string, any>

            expect(result.retention_window_days).toBe(expected)
        })

        it('includes has_breakdown when breakdownFilter is set', () => {
            const metric: ExperimentMeanMetric = {
                kind: NodeKind.ExperimentMetric,
                metric_type: 'mean' as const,
                source: { kind: NodeKind.EventsNode, event: 'purchase' },
                breakdownFilter: { breakdown: '$browser', breakdown_type: 'event' },
            } as ExperimentMeanMetric

            const result = getEventPropertiesForMetric(metric) as Record<string, any>

            expect(result.has_breakdown).toBe(true)
        })

        it('returns base properties for unknown metric_type', () => {
            const metric = {
                kind: NodeKind.ExperimentMetric,
                metric_type: 'some_future_type',
            }

            const result = getEventPropertiesForMetric(metric as any) as Record<string, any>

            expect(result).toEqual({
                kind: NodeKind.ExperimentMetric,
                metric_type: 'some_future_type',
                has_breakdown: false,
            })
        })

        it('handles empty funnel series', () => {
            const metric: ExperimentFunnelMetric = {
                kind: NodeKind.ExperimentMetric,
                metric_type: 'funnel' as const,
                series: [],
            } as ExperimentFunnelMetric

            const result = getEventPropertiesForMetric(metric) as Record<string, any>

            expect(result.funnel_steps_count).toBe(0)
            expect(result.property_filter_count).toBe(0)
        })
    })

    describe('legacy formats', () => {
        it('extracts ExperimentFunnelsQuery properties', () => {
            const metric = {
                kind: NodeKind.ExperimentFunnelsQuery,
                funnels_query: {
                    series: [
                        { kind: NodeKind.EventsNode },
                        { kind: NodeKind.EventsNode },
                        { kind: NodeKind.EventsNode },
                    ],
                    filterTestAccounts: true,
                },
            } as ExperimentFunnelsQuery

            const result = getEventPropertiesForMetric(metric) as Record<string, any>

            expect(result.kind).toBe(NodeKind.ExperimentFunnelsQuery)
            expect(result.steps_count).toBe(3)
            expect(result.filter_test_accounts).toBe(true)
        })

        it('extracts ExperimentTrendsQuery properties', () => {
            const metric = {
                kind: NodeKind.ExperimentTrendsQuery,
                count_query: {
                    series: [{ kind: NodeKind.ActionsNode, id: 1 }],
                    filterTestAccounts: false,
                },
            } as ExperimentTrendsQuery

            const result = getEventPropertiesForMetric(metric) as Record<string, any>

            expect(result.kind).toBe(NodeKind.ExperimentTrendsQuery)
            expect(result.series_kind).toBe(NodeKind.ActionsNode)
            expect(result.filter_test_accounts).toBe(false)
        })
    })
})
