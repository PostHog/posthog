import { EXPERIMENT_DEFAULT_DURATION, FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import experimentJson from '~/mocks/fixtures/api/experiments/_experiment_launched_with_funnel_and_trends.json'
import EXPERIMENT_V3_WITH_ONE_EXPERIMENT_QUERY from '~/mocks/fixtures/api/experiments/_experiment_v3_with_one_metric.json'
import metricFunnelEventsJson from '~/mocks/fixtures/api/experiments/_metric_funnel_events.json'
import metricTrendActionJson from '~/mocks/fixtures/api/experiments/_metric_trend_action.json'
import metricTrendCustomExposureJson from '~/mocks/fixtures/api/experiments/_metric_trend_custom_exposure.json'
import metricTrendFeatureFlagCalledJson from '~/mocks/fixtures/api/experiments/_metric_trend_feature_flag_called.json'
import {
    ActionsNode,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentEventExposureConfig,
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentMetricType,
    ExperimentTrendsQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import {
    ChartDisplayType,
    Experiment,
    ExperimentMetricMathType,
    FeatureFlagFilters,
    FeatureFlagType,
    PropertyFilterType,
    PropertyMathType,
    PropertyOperator,
} from '~/types'

import { getNiceTickValues } from './MetricsView/MetricsView'
import { SharedMetric } from './SharedMetrics/sharedMetricLogic'
import {
    exposureConfigToFilter,
    featureFlagEligibleForExperiment,
    filterToExposureConfig,
    filterToMetricConfig,
    getViewRecordingFilters,
    isLegacyExperiment,
    isLegacyExperimentQuery,
    isLegacySharedMetric,
    metricToFilter,
    metricToQuery,
    percentageDistribution,
    transformFiltersForWinningVariant,
} from './utils'

describe('utils', () => {
    describe('percentageDistribution', () => {
        it('given variant count, calculates correct rollout percentages', async () => {
            expect(percentageDistribution(1)).toEqual([100])
            expect(percentageDistribution(2)).toEqual([50, 50])
            expect(percentageDistribution(3)).toEqual([34, 33, 33])
            expect(percentageDistribution(4)).toEqual([25, 25, 25, 25])
            expect(percentageDistribution(5)).toEqual([20, 20, 20, 20, 20])
            expect(percentageDistribution(6)).toEqual([17, 17, 17, 17, 16, 16])
            expect(percentageDistribution(7)).toEqual([15, 15, 14, 14, 14, 14, 14])
            expect(percentageDistribution(8)).toEqual([13, 13, 13, 13, 12, 12, 12, 12])
            expect(percentageDistribution(9)).toEqual([12, 11, 11, 11, 11, 11, 11, 11, 11])
            expect(percentageDistribution(10)).toEqual([10, 10, 10, 10, 10, 10, 10, 10, 10, 10])
            expect(percentageDistribution(11)).toEqual([10, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9])
            expect(percentageDistribution(12)).toEqual([9, 9, 9, 9, 8, 8, 8, 8, 8, 8, 8, 8])
            expect(percentageDistribution(13)).toEqual([8, 8, 8, 8, 8, 8, 8, 8, 8, 7, 7, 7, 7])
            expect(percentageDistribution(14)).toEqual([8, 8, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7])
            expect(percentageDistribution(15)).toEqual([7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 6, 6, 6, 6, 6])
            expect(percentageDistribution(16)).toEqual([7, 7, 7, 7, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6])
            expect(percentageDistribution(17)).toEqual([6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 5, 5])
            expect(percentageDistribution(18)).toEqual([6, 6, 6, 6, 6, 6, 6, 6, 6, 6, 5, 5, 5, 5, 5, 5, 5, 5])
            expect(percentageDistribution(19)).toEqual([6, 6, 6, 6, 6, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5])
            expect(percentageDistribution(20)).toEqual([5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5])
        })
    })

    it('transforms filters for a winning variant', async () => {
        let currentFilters: FeatureFlagFilters = {
            groups: [
                {
                    properties: [],
                    rollout_percentage: 100,
                },
            ],
            payloads: {},
            multivariate: {
                variants: [
                    {
                        key: 'control',
                        rollout_percentage: 50,
                    },
                    {
                        key: 'test',
                        rollout_percentage: 50,
                    },
                ],
            },
            aggregation_group_type_index: null,
        }
        let expectedFilters: FeatureFlagFilters = {
            aggregation_group_type_index: null,
            payloads: {},
            multivariate: {
                variants: [
                    { key: 'control', rollout_percentage: 0 },
                    { key: 'test', rollout_percentage: 100 },
                ],
            },
            groups: [
                { properties: [], rollout_percentage: 100 },
                { properties: [], rollout_percentage: 100 },
            ],
        }

        let newFilters = transformFiltersForWinningVariant(currentFilters, 'test')
        expect(newFilters).toEqual(expectedFilters)

        currentFilters = {
            groups: [
                {
                    properties: [],
                    rollout_percentage: 100,
                },
            ],
            payloads: {
                test_1: "{key: 'test_1'}",
                test_2: "{key: 'test_2'}",
                test_3: "{key: 'test_3'}",
                control: "{key: 'control'}",
            },
            multivariate: {
                variants: [
                    {
                        key: 'control',
                        name: 'This is control',
                        rollout_percentage: 25,
                    },
                    {
                        key: 'test_1',
                        name: 'This is test_1',
                        rollout_percentage: 25,
                    },
                    {
                        key: 'test_2',
                        name: 'This is test_2',
                        rollout_percentage: 25,
                    },
                    {
                        key: 'test_3',
                        name: 'This is test_3',
                        rollout_percentage: 25,
                    },
                ],
            },
            aggregation_group_type_index: 1,
        }
        expectedFilters = {
            aggregation_group_type_index: 1,
            payloads: {
                test_1: "{key: 'test_1'}",
                test_2: "{key: 'test_2'}",
                test_3: "{key: 'test_3'}",
                control: "{key: 'control'}",
            },
            multivariate: {
                variants: [
                    {
                        key: 'control',
                        name: 'This is control',
                        rollout_percentage: 100,
                    },
                    {
                        key: 'test_1',
                        name: 'This is test_1',
                        rollout_percentage: 0,
                    },
                    {
                        key: 'test_2',
                        name: 'This is test_2',
                        rollout_percentage: 0,
                    },
                    {
                        key: 'test_3',
                        name: 'This is test_3',
                        rollout_percentage: 0,
                    },
                ],
            },
            groups: [
                { properties: [], rollout_percentage: 100 },
                { properties: [], rollout_percentage: 100 },
            ],
        }

        newFilters = transformFiltersForWinningVariant(currentFilters, 'control')
        expect(newFilters).toEqual(expectedFilters)
    })
})

describe('getNiceTickValues', () => {
    it('generates appropriate tick values for different ranges', () => {
        // Small values (< 0.1)
        expect(getNiceTickValues(0.08)).toEqual([-0.1, -0.08, -0.06, -0.04, -0.02, 0, 0.02, 0.04, 0.06, 0.08, 0.1])

        // Medium small values (0.1 - 1)
        expect(getNiceTickValues(0.45)).toEqual([-0.5, -0.4, -0.3, -0.2, -0.1, 0, 0.1, 0.2, 0.3, 0.4, 0.5])

        // Values around 1
        expect(getNiceTickValues(1.2)).toEqual([-1.5, -1.0, -0.5, 0, 0.5, 1.0, 1.5])

        // Values around 5
        expect(getNiceTickValues(4.7)).toEqual([-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5])

        // Larger values
        expect(getNiceTickValues(8.5)).toEqual([-10, -8, -6, -4, -2, 0, 2, 4, 6, 8, 10])
    })
})

describe('getViewRecordingFilters', () => {
    const featureFlagKey = 'jan-16-running'

    it('returns the correct filters for an experiment query', () => {
        const filters = getViewRecordingFilters(
            EXPERIMENT_V3_WITH_ONE_EXPERIMENT_QUERY.metrics[0] as ExperimentMetric,
            featureFlagKey,
            'control'
        )
        expect(filters).toEqual([
            {
                id: 'storybook-click',
                name: 'storybook-click',
                type: 'events',
                properties: [
                    {
                        key: `$feature/${featureFlagKey}`,
                        type: PropertyFilterType.Event,
                        value: ['control'],
                        operator: PropertyOperator.Exact,
                    },
                ],
            },
        ])
    })

    it('returns the correct filters for a funnel metric', () => {
        const filters = getViewRecordingFilters(
            metricFunnelEventsJson as ExperimentFunnelsQuery,
            featureFlagKey,
            'control'
        )
        expect(filters).toEqual([
            {
                id: '[jan-16-running] seen',
                name: '[jan-16-running] seen',
                type: 'events',
                properties: [
                    {
                        key: `$feature/${featureFlagKey}`,
                        type: PropertyFilterType.Event,
                        value: ['control'],
                        operator: PropertyOperator.Exact,
                    },
                ],
            },
            {
                id: '[jan-16-running] payment',
                name: '[jan-16-running] payment',
                type: 'events',
                properties: [
                    {
                        key: `$feature/${featureFlagKey}`,
                        type: PropertyFilterType.Event,
                        value: ['control'],
                        operator: PropertyOperator.Exact,
                    },
                ],
            },
        ])
    })
    it('returns the correct filters for a trend metric', () => {
        const filters = getViewRecordingFilters(
            metricTrendFeatureFlagCalledJson as ExperimentTrendsQuery,
            featureFlagKey,
            'test'
        )
        expect(filters).toEqual([
            {
                id: '$feature_flag_called',
                name: '$feature_flag_called',
                type: 'events',
                properties: [
                    {
                        key: '$feature_flag_response',
                        type: PropertyFilterType.Event,
                        value: ['test'],
                        operator: PropertyOperator.Exact,
                    },
                    {
                        key: '$feature_flag',
                        type: PropertyFilterType.Event,
                        value: 'jan-16-running',
                        operator: PropertyOperator.Exact,
                    },
                ],
            },
            {
                id: '[jan-16-running] event one',
                name: '[jan-16-running] event one',
                type: 'events',
                properties: [
                    {
                        key: `$feature/${featureFlagKey}`,
                        type: PropertyFilterType.Event,
                        value: ['test'],
                        operator: PropertyOperator.Exact,
                    },
                ],
            },
        ])
    })
    it('returns the correct filters for a trend metric with custom exposure', () => {
        const filters = getViewRecordingFilters(
            metricTrendCustomExposureJson as ExperimentTrendsQuery,
            featureFlagKey,
            'test'
        )
        expect(filters).toEqual([
            {
                id: '[jan-16-running] event zero',
                name: '[jan-16-running] event zero',
                type: 'events',
                properties: [
                    {
                        key: `$feature/${featureFlagKey}`,
                        type: PropertyFilterType.Event,
                        value: ['test'],
                        operator: PropertyOperator.Exact,
                    },
                ],
            },
            {
                id: '[jan-16-running] event one',
                name: '[jan-16-running] event one',
                type: 'events',
                properties: [
                    {
                        key: `$feature/${featureFlagKey}`,
                        type: PropertyFilterType.Event,
                        value: ['test'],
                        operator: PropertyOperator.Exact,
                    },
                ],
            },
        ])
    })
    it('returns the correct filters for a trend metric with an action', () => {
        const filters = getViewRecordingFilters(metricTrendActionJson as ExperimentTrendsQuery, featureFlagKey, 'test')
        expect(filters).toEqual([
            {
                id: '$feature_flag_called',
                name: '$feature_flag_called',
                type: 'events',
                properties: [
                    {
                        key: '$feature_flag_response',
                        type: PropertyFilterType.Event,
                        value: ['test'],
                        operator: PropertyOperator.Exact,
                    },
                    {
                        key: '$feature_flag',
                        type: PropertyFilterType.Event,
                        value: 'jan-16-running',
                        operator: PropertyOperator.Exact,
                    },
                ],
            },
            {
                id: 8,
                name: 'jan-16-running payment action',
                type: 'actions',
            },
        ])
    })
})

describe('checkFeatureFlagEligibility', () => {
    const baseFeatureFlag: FeatureFlagType = {
        id: 1,
        key: 'test',
        name: 'Test',
        created_at: '2021-01-01',
        created_by: null,
        is_simple_flag: false,
        is_remote_configuration: false,
        filters: {
            groups: [],
            payloads: {},
            multivariate: null,
        },
        deleted: false,
        active: true,
        rollout_percentage: null,
        experiment_set: null,
        features: null,
        surveys: null,
        rollback_conditions: [],
        performed_rollback: false,
        can_edit: true,
        tags: [],
        ensure_experience_continuity: null,
        user_access_level: 'admin',
        status: 'ACTIVE',
        has_encrypted_payloads: false,
        version: 0,
        last_modified_by: null,
    }
    it('throws an error for a remote configuration feature flag', () => {
        const featureFlag = { ...baseFeatureFlag, is_remote_configuration: true }
        expect(() => featureFlagEligibleForExperiment(featureFlag)).toThrow(
            'Feature flag must use multiple variants with control as the first variant.'
        )
    })
    it('throws an error for a feature flag without control as the first variant', () => {
        const featureFlag = {
            ...baseFeatureFlag,
            filters: {
                ...baseFeatureFlag.filters,
                multivariate: {
                    variants: [
                        { key: 'foobar', rollout_percentage: 50 },
                        { key: 'control', rollout_percentage: 50 },
                    ],
                },
            },
        }
        expect(() => featureFlagEligibleForExperiment(featureFlag)).toThrow(
            'Feature flag must have control as the first variant.'
        )
    })
    it('throws an error for a feature flag with only one variant', () => {
        const featureFlag = {
            ...baseFeatureFlag,
            filters: {
                ...baseFeatureFlag.filters,
                multivariate: { variants: [{ key: 'test', rollout_percentage: 50 }] },
            },
        }
        expect(() => featureFlagEligibleForExperiment(featureFlag)).toThrow(
            'Feature flag must use multiple variants with control as the first variant.'
        )
    })
    it('returns true for a feature flag with control and test variants', () => {
        const featureFlag = {
            ...baseFeatureFlag,
            filters: {
                ...baseFeatureFlag.filters,
                multivariate: {
                    variants: [
                        { key: 'control', rollout_percentage: 50 },
                        { key: 'test', rollout_percentage: 50 },
                    ],
                },
            },
        }
        expect(featureFlagEligibleForExperiment(featureFlag)).toEqual(true)
    })
})

describe('exposureConfigToFilter', () => {
    it('returns the correct filter for an exposure config', () => {
        const exposureConfig = {
            kind: NodeKind.ExperimentEventExposureConfig,
            event: '$feature_flag_called',
            properties: [
                {
                    key: '$feature_flag_response',
                    value: ['test'],
                    operator: 'exact',
                    type: 'event',
                },
            ],
        } as ExperimentEventExposureConfig
        const filter = exposureConfigToFilter(exposureConfig)
        expect(filter).toEqual({
            events: [
                {
                    id: '$feature_flag_called',
                    name: '$feature_flag_called',
                    kind: 'EventsNode',
                    type: 'events',
                    properties: [
                        {
                            key: '$feature_flag_response',
                            value: ['test'],
                            operator: 'exact',
                            type: 'event',
                        },
                    ],
                },
            ],
            actions: [],
            data_warehouse: [],
        })
    })
})

describe('filterToExposureConfig', () => {
    it('returns the correct exposure config for an event', () => {
        const event = {
            id: '$feature_flag_called',
            name: '$feature_flag_called',
            kind: 'EventsNode',
            type: 'events',
            properties: [
                {
                    key: '$feature_flag_response',
                    value: ['test'],
                    operator: 'exact',
                    type: 'event',
                },
            ],
        }
        const exposureConfig = filterToExposureConfig(event)
        expect(exposureConfig).toEqual({
            kind: NodeKind.ExperimentEventExposureConfig,
            event: '$feature_flag_called',
            properties: [
                {
                    key: '$feature_flag_response',
                    value: ['test'],
                    operator: 'exact',
                    type: 'event',
                },
            ],
        })
    })
})

describe('metricToFilter', () => {
    it('returns the correct filter for an event', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                math: 'total',
                math_property: undefined,
                math_hogql: undefined,
                properties: [{ key: '$browser', value: ['Chrome'], operator: 'exact', type: 'event' }],
            } as EventsNode,
        }
        const filter = metricToFilter(metric)
        expect(filter).toEqual({
            events: [
                {
                    id: '$pageview',
                    name: '$pageview',
                    type: 'events',
                    math: 'total',
                    math_property: undefined,
                    math_hogql: undefined,
                    properties: [{ key: '$browser', value: ['Chrome'], operator: 'exact', type: 'event' }],
                    kind: NodeKind.EventsNode,
                },
            ],
            actions: [],
            data_warehouse: [],
        })
    })
    it('returns the correct filter for an action', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.ActionsNode,
                id: 8,
                name: 'jan-16-running payment action',
                math: 'total',
                math_property: undefined,
                math_hogql: undefined,
                properties: [{ key: '$lib', type: 'event', value: ['python'], operator: 'exact' }],
            } as ActionsNode,
        }
        const filter = metricToFilter(metric)
        expect(filter).toEqual({
            events: [],
            actions: [
                {
                    id: 8,
                    name: 'jan-16-running payment action',
                    type: 'actions',
                    math: 'total',
                    math_property: undefined,
                    math_hogql: undefined,
                    properties: [{ key: '$lib', type: 'event', value: ['python'], operator: 'exact' }],
                    kind: NodeKind.ActionsNode,
                },
            ],
            data_warehouse: [],
        })
    })
    it('returns the correct filter for a data warehouse metric', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.ExperimentDataWarehouseNode,
                table_name: 'mysql_payments',
                name: 'mysql_payments',
                timestamp_field: 'timestamp',
                events_join_key: 'person.properties.email',
                data_warehouse_join_key: 'customer.email',
                math: ExperimentMetricMathType.TotalCount,
                math_property: undefined,
                math_hogql: undefined,
            } as ExperimentDataWarehouseNode,
        }
        const filter = metricToFilter(metric)
        expect(filter).toEqual({
            events: [],
            actions: [],
            data_warehouse: [
                {
                    kind: NodeKind.ExperimentDataWarehouseNode,
                    id: undefined,
                    name: 'mysql_payments',
                    type: 'data_warehouse',
                    timestamp_field: 'timestamp',
                    events_join_key: 'person.properties.email',
                    data_warehouse_join_key: 'customer.email',
                    math: ExperimentMetricMathType.TotalCount,
                    math_property: undefined,
                    math_hogql: undefined,
                    properties: undefined,
                },
            ],
        })
    })
})

describe('filterToMetricConfig', () => {
    it('returns the correct metric config for an event', () => {
        const event = {
            kind: NodeKind.EventsNode,
            id: '$pageview',
            name: '$pageview',
            type: 'events',
            order: 0,
            uuid: 'b2aa47bc-c39b-4743-a2a2-ab88f78faf11',
            properties: [
                {
                    key: '$browser',
                    value: ['Chrome'],
                    operator: 'exact',
                    type: 'event',
                },
            ],
        } as Record<string, any>
        const metricConfig = filterToMetricConfig(ExperimentMetricType.MEAN, undefined, [event], undefined)
        expect(metricConfig).toEqual({
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                math: 'total',
                math_property: undefined,
                math_hogql: undefined,
                properties: [
                    {
                        key: '$browser',
                        value: ['Chrome'],
                        operator: 'exact',
                        type: 'event',
                    },
                ],
            },
        })
    })
    it('returns the correct metric config for an action', () => {
        const action = {
            id: '8',
            name: 'jan-16-running payment action',
            kind: NodeKind.ActionsNode,
            type: 'actions',
            math: 'total',
            properties: [
                {
                    key: '$lib',
                    type: 'event',
                    value: ['python'],
                    operator: 'exact',
                },
            ],
            order: 0,
            uuid: '29c01ac4-ebc3-4cb8-9d82-287c0487056e',
        } as Record<string, any>
        const metricConfig = filterToMetricConfig(ExperimentMetricType.MEAN, [action], undefined, undefined)
        expect(metricConfig).toEqual({
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.ActionsNode,
                id: '8',
                name: 'jan-16-running payment action',
                math: 'total',
                math_property: undefined,
                math_hogql: undefined,
                properties: [{ key: '$lib', type: 'event', value: ['python'], operator: 'exact' }],
            },
        })
    })
    it('returns the correct metric config for a data warehouse metric', () => {
        const dataWarehouse = {
            kind: NodeKind.EventsNode,
            id: 'mysql_payments',
            name: 'mysql_payments',
            type: 'data_warehouse',
            timestamp_field: 'timestamp',
            events_join_key: 'person.properties.email',
            data_warehouse_join_key: 'customer.email',
        } as Record<string, any>
        const metricConfig = filterToMetricConfig(ExperimentMetricType.MEAN, undefined, undefined, [dataWarehouse])
        expect(metricConfig).toEqual({
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.ExperimentDataWarehouseNode,
                table_name: 'mysql_payments',
                name: 'mysql_payments',
                timestamp_field: 'timestamp',
                events_join_key: 'person.properties.email',
                data_warehouse_join_key: 'customer.email',
                math: ExperimentMetricMathType.TotalCount,
                math_property: undefined,
                math_hogql: undefined,
            },
        })
    })
})

describe('metricToQuery', () => {
    it('returns the correct query for a funnel metric', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.FUNNEL,
            series: [
                {
                    event: 'purchase',
                    kind: NodeKind.EventsNode,
                    name: 'purchase',
                },
            ],
        }

        const query = metricToQuery(metric, false)
        expect(query).toEqual({
            kind: NodeKind.FunnelsQuery,
            dateRange: {
                date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                explicitDate: true,
            },
            funnelsFilter: {
                layout: FunnelLayout.horizontal,
            },
            filterTestAccounts: false,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                    custom_name: 'Placeholder for experiment exposure',
                },
                {
                    kind: NodeKind.EventsNode,
                    event: 'purchase',
                    name: 'purchase',
                },
            ],
        })
    })

    it('returns the correct query for a count metric', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
            },
        }

        const query = metricToQuery(metric, false)
        expect(query).toEqual({
            kind: NodeKind.TrendsQuery,
            interval: 'day',
            dateRange: {
                date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                explicitDate: true,
            },
            trendsFilter: {
                display: ChartDisplayType.ActionsLineGraph,
            },
            filterTestAccounts: false,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    name: '$pageview',
                    event: '$pageview',
                },
            ],
        })
    })

    it('returns the correct query for a mean metric with sum math type', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                math: ExperimentMetricMathType.Sum,
                math_property: 'property_value',
            },
        }

        const query = metricToQuery(metric, true)
        expect(query).toEqual({
            kind: NodeKind.TrendsQuery,
            interval: 'day',
            dateRange: {
                date_from: dayjs().subtract(EXPERIMENT_DEFAULT_DURATION, 'day').format('YYYY-MM-DDTHH:mm'),
                date_to: dayjs().endOf('d').format('YYYY-MM-DDTHH:mm'),
                explicitDate: true,
            },
            trendsFilter: {
                display: ChartDisplayType.ActionsLineGraph,
            },
            filterTestAccounts: true,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: '$pageview',
                    name: '$pageview',
                    math: PropertyMathType.Sum,
                    math_property: 'property_value',
                },
            ],
        })
    })

    it('returns undefined for unsupported metric types', () => {
        const metric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: 'unsupported_type' as ExperimentMetricType,
            source: {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
            },
        }

        const query = metricToQuery(metric as ExperimentMetric, false)
        expect(query).toBeUndefined()
    })
})

describe('isLegacyExperimentQuery', () => {
    it('returns true for ExperimentTrendsQuery', () => {
        const query = {
            kind: NodeKind.ExperimentTrendsQuery,
            count_query: {
                kind: NodeKind.TrendsQuery,
                series: [],
            },
        }
        expect(isLegacyExperimentQuery(query)).toBe(true)
    })

    it('returns true for ExperimentFunnelsQuery', () => {
        const query = {
            kind: NodeKind.ExperimentFunnelsQuery,
            funnels_query: {
                kind: NodeKind.FunnelsQuery,
                series: [],
            },
        }
        expect(isLegacyExperimentQuery(query)).toBe(true)
    })

    it('returns false for ExperimentMetric', () => {
        const query = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: 'test',
            },
        }
        expect(isLegacyExperimentQuery(query)).toBe(false)
    })

    it('returns false for null/undefined', () => {
        expect(isLegacyExperimentQuery(null)).toBe(false)
        expect(isLegacyExperimentQuery(undefined)).toBe(false)
    })

    it('returns false for non-object values', () => {
        expect(isLegacyExperimentQuery('string')).toBe(false)
        expect(isLegacyExperimentQuery(123)).toBe(false)
    })
})

describe('hasLegacyMetrics', () => {
    it('returns true if experiment has legacy metrics', () => {
        const experiment = {
            ...experimentJson,
            metrics: [
                {
                    kind: NodeKind.ExperimentTrendsQuery,
                    count_query: { kind: NodeKind.TrendsQuery, series: [] },
                },
            ],
            metrics_secondary: [],
            saved_metrics: [],
        } as unknown as Experiment

        expect(isLegacyExperiment(experiment)).toBe(true)
    })

    it('returns true if experiment has legacy secondary metrics', () => {
        const experiment = {
            ...experimentJson,
            metrics: [],
            metrics_secondary: [
                {
                    kind: NodeKind.ExperimentFunnelsQuery,
                    funnels_query: { kind: NodeKind.FunnelsQuery, series: [] },
                },
            ],
            saved_metrics: [],
        } as unknown as Experiment

        expect(isLegacyExperiment(experiment)).toBe(true)
    })

    it('returns true if experiment has legacy saved metrics', () => {
        const experiment = {
            ...experimentJson,
            metrics: [],
            metrics_secondary: [],
            saved_metrics: [
                {
                    kind: NodeKind.ExperimentTrendsQuery,
                    count_query: { kind: NodeKind.TrendsQuery, series: [] },
                },
            ],
        } as unknown as Experiment

        expect(isLegacyExperiment(experiment)).toBe(true)
    })

    it('returns false if experiment has no legacy metrics', () => {
        const experiment = {
            ...experimentJson,
            metrics: [
                {
                    kind: NodeKind.ExperimentMetric,
                    metric_type: ExperimentMetricType.MEAN,
                    source: { kind: NodeKind.EventsNode, event: 'test' },
                },
            ],
            metrics_secondary: [],
            saved_metrics: [],
        } as unknown as Experiment

        expect(isLegacyExperiment(experiment)).toBe(false)
    })

    it('returns false if experiment has no metrics', () => {
        const experiment = {
            ...experimentJson,
            metrics: [],
            metrics_secondary: [],
            saved_metrics: [],
        } as unknown as Experiment

        expect(isLegacyExperiment(experiment)).toBe(false)
    })
})

describe('hasLegacySharedMetrics', () => {
    it('returns true if shared metrics contain legacy query', () => {
        const sharedMetric = {
            query: {
                kind: NodeKind.ExperimentTrendsQuery,
                count_query: { kind: NodeKind.TrendsQuery, series: [] },
            },
        } as unknown as SharedMetric

        expect(isLegacySharedMetric(sharedMetric)).toBe(true)
    })

    it('returns false if shared metrics contain no legacy queries', () => {
        const sharedMetric = {
            query: {
                kind: NodeKind.ExperimentMetric,
                metric_type: ExperimentMetricType.MEAN,
                source: { kind: NodeKind.EventsNode, event: 'test' },
            },
        } as unknown as SharedMetric

        expect(isLegacySharedMetric(sharedMetric)).toBe(false)
    })

    it('returns false for empty shared metrics array', () => {
        expect(isLegacySharedMetric({} as SharedMetric)).toBe(false)
    })
})
