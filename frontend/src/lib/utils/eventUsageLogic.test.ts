import posthog from 'posthog-js'

import { SELF_DRIVING_ONBOARDING_EVENT_PROPS } from 'scenes/onboarding/onboardingEventUsageLogic'

import { NodeKind } from '~/queries/schema/schema-general'
import type {
    ExperimentFunnelMetric,
    ExperimentFunnelsQuery,
    ExperimentMeanMetric,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    ExperimentTrendsQuery,
    Node,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import {
    BaseMathType,
    BehavioralEventType,
    ChartDisplayType,
    type DashboardTile,
    type DashboardType,
    FilterLogicalOperator,
    FunnelVizType,
    PropertyFilterType,
    type QueryBasedInsightModel,
    StepOrderValue,
} from '~/types'

import {
    type OnboardingEventProperties,
    dashboardViewedProperties,
    eventUsageLogic,
    getEventPropertiesForMetric,
    sanitizeQuery,
} from './eventUsageLogic'

describe('eventUsageLogic', () => {
    describe('onboarding funnel events', () => {
        let capture: jest.SpyInstance

        beforeEach(() => {
            initKeaTests()
            eventUsageLogic.mount()
            capture = jest.spyOn(posthog, 'capture').mockImplementation()
        })

        afterEach(() => {
            capture.mockRestore()
        })

        const cases: [string, OnboardingEventProperties | undefined, string][] = [
            ['legacy', undefined, 'product_selection'],
            ['self-driving', SELF_DRIVING_ONBOARDING_EVENT_PROPS, 'welcome'],
        ]

        it.each(cases)('stamps the %s entry point on every funnel event', (_, properties, entryPoint) => {
            eventUsageLogic.actions.reportOnboardingStarted(properties)
            eventUsageLogic.actions.reportOnboardingStepCompleted('install', undefined, properties)
            eventUsageLogic.actions.reportOnboardingStepSkipped('install', undefined, properties)
            eventUsageLogic.actions.reportOnboardingCompleted('product_analytics', properties)

            for (const event of [
                'onboarding started',
                'onboarding step completed',
                'onboarding step skipped',
                'onboarding completed',
            ]) {
                const call = capture.mock.calls.find(([name]) => name === event)
                expect(call?.[1]).toMatchObject({ entry_point: entryPoint })
            }
        })
    })

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

    describe('sanitizeQuery', () => {
        it('counts behavioral filters across global and series filters', () => {
            const query = {
                kind: NodeKind.InsightVizNode,
                source: {
                    kind: NodeKind.TrendsQuery,
                    series: [
                        {
                            kind: NodeKind.EventsNode,
                            event: '$pageview',
                            properties: [
                                {
                                    type: PropertyFilterType.Behavioral,
                                    key: 'signed up',
                                    value: BehavioralEventType.PerformEvent,
                                    event_type: 'events',
                                },
                            ],
                        },
                    ],
                    properties: {
                        type: FilterLogicalOperator.And,
                        values: [
                            {
                                type: FilterLogicalOperator.And,
                                values: [
                                    {
                                        type: PropertyFilterType.Behavioral,
                                        key: 'completed onboarding',
                                        value: BehavioralEventType.PerformEvent,
                                        event_type: 'events',
                                    },
                                ],
                            },
                        ],
                    },
                },
            } as unknown as Node

            expect(sanitizeQuery(query).behavioral_filter_count).toBe(2)
        })

        const trendsSource = {
            kind: NodeKind.TrendsQuery,
            dateRange: { date_from: '-7d', date_to: null },
            interval: 'day',
            samplingFactor: 0.1,
            filterTestAccounts: true,
            series: [
                { kind: NodeKind.EventsNode, event: '$pageview' },
                { kind: NodeKind.ActionsNode, id: 1 },
                { kind: NodeKind.DataWarehouseNode, table_name: 'orders' },
            ],
            breakdownFilter: { breakdown_type: 'event', breakdown_limit: 5, breakdown_hide_other_aggregation: true },
            compareFilter: { compare: true, compare_to: '-1w' },
            trendsFilter: { formula: 'A + B' },
        }
        const trendsProperties = {
            uses_data_warehouse_source: true,
            date_from: '-7d',
            interval: 'day',
            samplingFactor: 0.1,
            series_length: 3,
            event_entity_count: 1,
            action_entity_count: 1,
            data_warehouse_entity_count: 1,
            has_properties: false,
            behavioral_filter_count: 0,
            filter_test_accounts: true,
            breakdown_type: 'event',
            breakdown_limit: 5,
            breakdown_hide_other_aggregation: true,
            has_formula: true,
            display: ChartDisplayType.ActionsLineGraph,
            compare: true,
            compare_to: '-1w',
        }
        const funnelsSource = {
            kind: NodeKind.FunnelsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
            funnelsFilter: { funnelVizType: FunnelVizType.Steps, funnelOrderType: StepOrderValue.STRICT },
        }

        const cases: [string, unknown, Record<string, unknown>][] = [
            ['null', null, { uses_data_warehouse_source: false }],
            [
                'a trends query wrapped in an InsightVizNode',
                { kind: NodeKind.InsightVizNode, source: trendsSource },
                { query_kind: NodeKind.InsightVizNode, query_source_kind: NodeKind.TrendsQuery, ...trendsProperties },
            ],
            ['a bare trends query', trendsSource, { query_kind: NodeKind.TrendsQuery, ...trendsProperties }],
            [
                'a funnels query',
                funnelsSource,
                {
                    query_kind: NodeKind.FunnelsQuery,
                    uses_data_warehouse_source: false,
                    series_length: 1,
                    event_entity_count: 1,
                    action_entity_count: 0,
                    data_warehouse_entity_count: 0,
                    has_properties: false,
                    behavioral_filter_count: 0,
                    has_formula: false,
                    funnel_viz_type: FunnelVizType.Steps,
                    funnel_order_type: StepOrderValue.STRICT,
                },
            ],
            [
                'a non-insight query',
                { kind: NodeKind.DataTableNode, source: { kind: NodeKind.HogQLQuery, query: 'select 1' } },
                {
                    query_kind: NodeKind.DataTableNode,
                    query_source_kind: NodeKind.HogQLQuery,
                    uses_data_warehouse_source: false,
                },
            ],
        ]

        it.each(cases)('describes %s without its filter values', (_, query, expected) => {
            expect(sanitizeQuery(query as Node | null)).toEqual(expected)
        })
    })

    describe('dashboardViewedProperties', () => {
        const dashboard = (
            tiles: Partial<DashboardTile<QueryBasedInsightModel>>[]
        ): DashboardType<QueryBasedInsightModel> =>
            ({
                id: 7,
                created_at: '2026-01-01T00:00:00Z',
                is_shared: false,
                pinned: true,
                creation_mode: 'default',
                created_by: { uuid: 'creator' },
                tiles,
            }) as unknown as DashboardType<QueryBasedInsightModel>

        const insightTile = (query: unknown, is_sample = false): Partial<DashboardTile<QueryBasedInsightModel>> =>
            ({ insight: { query, is_sample } }) as unknown as Partial<DashboardTile<QueryBasedInsightModel>>

        const cases: [string, Partial<DashboardTile<QueryBasedInsightModel>>[], Record<string, unknown>][] = [
            ['no tiles', [], { item_count: 0, sample_items_count: 0 }],
            [
                'an insight tile with a query',
                [insightTile({ kind: NodeKind.InsightVizNode, source: { kind: NodeKind.TrendsQuery, series: [] } })],
                { item_count: 1, text_count: 1, uses_data_warehouse_source: false, data_warehouse_tiles_count: 0 },
            ],
            ['an insight tile without a query', [insightTile(null)], { item_count: 1, empty_count: 1 }],
            [
                'a sample insight tile that reads the warehouse',
                [insightTile({ kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.DataWarehouseNode }] }, true)],
                {
                    item_count: 1,
                    text_count: 1,
                    sample_items_count: 1,
                    uses_data_warehouse_source: true,
                    data_warehouse_tiles_count: 1,
                },
            ],
            [
                'text and widget tiles',
                [{ text: { body: 'hi' } }, { text: { body: 'there' } }, { widget: {} }] as Partial<
                    DashboardTile<QueryBasedInsightModel>
                >[],
                { item_count: 3, text_tiles_count: 2, widget_tiles_count: 1 },
            ],
        ]

        it.each(cases)('counts %s', (_, tiles, expected) => {
            expect(dashboardViewedProperties(dashboard(tiles), null, 'viewer')).toEqual({
                created_at: '2026-01-01T00:00:00Z',
                is_shared: false,
                pinned: true,
                creation_mode: 'default',
                viewer_is_creator: false,
                created_by_system: false,
                dashboard_id: 7,
                lastRefreshed: undefined,
                refreshAge: undefined,
                sample_items_count: 0,
                uses_data_warehouse_source: false,
                data_warehouse_tiles_count: 0,
                ...expected,
            })
        })

        const viewerCases: [string, { uuid: string } | null, string | undefined, boolean | undefined][] = [
            ['the creator views it', { uuid: 'creator' }, 'creator', true],
            ['another user views it', { uuid: 'creator' }, 'viewer', false],
            ['the viewer is unknown', { uuid: 'creator' }, undefined, undefined],
            ['the system created it', null, 'viewer', undefined],
        ]

        it.each(viewerCases)('reports viewer_is_creator when %s', (_, created_by, viewerUuid, expected) => {
            const withCreator = { ...dashboard([]), created_by } as unknown as DashboardType<QueryBasedInsightModel>
            expect(dashboardViewedProperties(withCreator, null, viewerUuid)).toMatchObject({
                viewer_is_creator: expected,
                created_by_system: created_by === null,
            })
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
