import experimentJson from '~/mocks/fixtures/api/experiments/_experiment_launched_with_funnel_and_trends.json'
import metricFunnelEventsJson from '~/mocks/fixtures/api/experiments/_metric_funnel_events.json'
import metricTrendActionJson from '~/mocks/fixtures/api/experiments/_metric_trend_action.json'
import metricTrendCustomExposureJson from '~/mocks/fixtures/api/experiments/_metric_trend_custom_exposure.json'
import metricTrendFeatureFlagCalledJson from '~/mocks/fixtures/api/experiments/_metric_trend_feature_flag_called.json'
import EXPERIMENT_WITH_MEAN_METRIC from '~/mocks/fixtures/api/experiments/experiment_with_mean_metric.json'
import {
    ExperimentEventExposureConfig,
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentMetricType,
    ExperimentTrendsQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    Experiment,
    ExperimentMetricMathType,
    FeatureFlagFilters,
    FeatureFlagType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { getNiceTickValues } from './MetricsView/shared/utils'
import {
    exposureConfigToFilter,
    featureFlagEligibleForExperiment,
    filterToExposureConfig,
    filterToMetricConfig,
    getViewRecordingFilters,
    getViewRecordingFiltersLegacy,
    isLegacyExperiment,
    isLegacyExperimentQuery,
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
        expect(getNiceTickValues(0.08)).toEqual([-0.08, -0.06, -0.04, -0.02, 0, 0.02, 0.04, 0.06, 0.08])

        // Medium small values (0.1 - 1)
        expect(getNiceTickValues(0.45)).toEqual([-0.4, -0.3, -0.2, -0.1, 0, 0.1, 0.2, 0.3, 0.4])

        // Values around 1
        expect(getNiceTickValues(1.2)).toEqual([-1, -0.5, 0, 0.5, 1])

        // Values around 5
        expect(getNiceTickValues(4.7)).toEqual([-4, -3, -2, -1, 0, 1, 2, 3, 4])

        // Larger values
        expect(getNiceTickValues(8.5)).toEqual([-6, -4, -2, 0, 2, 4, 6])
    })
})

describe('getViewRecordingFilters', () => {
    const experimentBase = {
        id: 1,
        name: 'test experiment',
        feature_flag_key: 'my-flag',
        exposure_criteria: undefined,
        filters: {},
        metrics: [],
        metrics_secondary: [],
        saved_metrics_ids: [],
        saved_metrics: [],
        parameters: {
            feature_flag_variants: [
                { key: 'control', rollout_percentage: 50 },
                { key: 'test', rollout_percentage: 50 },
            ],
        },
        secondary_metrics: [],
        created_at: null,
        created_by: null,
        updated_at: null,
    }

    it('adds exposure criteria if present', () => {
        const experiment = {
            ...experimentBase,
            exposure_criteria: {
                exposure_config: {
                    kind: NodeKind.ExperimentEventExposureConfig,
                    event: 'exposure_event',
                    properties: [
                        {
                            key: 'foo',
                            value: 'bar',
                            operator: PropertyOperator.IsNot,
                            type: PropertyFilterType.Event,
                        },
                    ],
                },
            },
        } satisfies Experiment

        const metric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: { kind: NodeKind.EventsNode, event: 'event1', name: 'event1' },
        } satisfies ExperimentMetric

        const filters = getViewRecordingFilters(experiment, metric, 'variantA')
        expect(filters[0]).toEqual({
            id: 'exposure_event',
            name: 'exposure_event',
            type: 'events',
            properties: [
                {
                    key: 'foo',
                    value: 'bar',
                    operator: PropertyOperator.IsNot,
                    type: PropertyFilterType.Event,
                },
                {
                    key: '$feature/my-flag',
                    type: PropertyFilterType.Event,
                    value: ['variantA'],
                    operator: PropertyOperator.Exact,
                },
            ],
        })
    })

    it('adds default exposure event if no exposure criteria', () => {
        const experiment = { ...experimentBase }
        const metric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: { kind: NodeKind.EventsNode, event: 'event1', name: 'event1' },
        } satisfies ExperimentMetric

        const filters = getViewRecordingFilters(experiment, metric, 'variantA')
        expect(filters[0]).toEqual({
            id: '$feature_flag_called',
            name: '$feature_flag_called',
            type: 'events',
            properties: [
                {
                    key: '$feature_flag_response',
                    type: PropertyFilterType.Event,
                    value: ['variantA'],
                    operator: PropertyOperator.Exact,
                },
                {
                    key: '$feature_flag',
                    type: PropertyFilterType.Event,
                    value: 'my-flag',
                    operator: PropertyOperator.Exact,
                },
            ],
        })
    })

    it('falls back to default exposure event if exposure_criteria exists but exposure_config is undefined', () => {
        const experiment = {
            ...experimentBase,
            exposure_criteria: {
                exposure_config: undefined,
            },
        } satisfies Experiment

        const metric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: { kind: NodeKind.EventsNode, event: 'event1', name: 'event1' },
        } satisfies ExperimentMetric

        const filters = getViewRecordingFilters(experiment, metric, 'variantA')
        expect(filters[0]).toEqual({
            id: '$feature_flag_called',
            name: '$feature_flag_called',
            type: 'events',
            properties: [
                {
                    key: '$feature_flag_response',
                    type: PropertyFilterType.Event,
                    value: ['variantA'],
                    operator: PropertyOperator.Exact,
                },
                {
                    key: '$feature_flag',
                    type: PropertyFilterType.Event,
                    value: 'my-flag',
                    operator: PropertyOperator.Exact,
                },
            ],
        })
    })

    it('adds mean metric event filter (no extra properties)', () => {
        const experiment = { ...experimentBase }
        const metric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: { kind: NodeKind.EventsNode, event: 'event1', name: 'event1' },
        } satisfies ExperimentMetric

        const filters = getViewRecordingFilters(experiment, metric, 'variantA')
        expect(filters[1]).toEqual({
            id: 'event1',
            name: 'event1',
            type: 'events',
            properties: [],
        })
    })

    it('adds mean metric event filter (with properties)', () => {
        const experiment = { ...experimentBase }
        const metric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: 'event1',
                name: 'event1',
                properties: [
                    { key: 'foo', value: 'bar', operator: PropertyOperator.Exact, type: PropertyFilterType.Event },
                ],
            },
        } satisfies ExperimentMetric

        const filters = getViewRecordingFilters(experiment, metric, 'variantA')
        expect(filters[1]).toEqual({
            id: 'event1',
            name: 'event1',
            type: 'events',
            properties: [
                {
                    key: 'foo',
                    value: 'bar',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                },
            ],
        })
    })

    it('adds mean metric action filter', () => {
        const experiment = { ...experimentBase }
        const metric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: { kind: NodeKind.ActionsNode, id: 123, name: 'action1' },
        } satisfies ExperimentMetric

        const filters = getViewRecordingFilters(experiment, metric, 'variantA')
        expect(filters[1]).toEqual({
            id: 123,
            name: 'action1',
            type: 'actions',
        })
    })

    it('adds funnel metric filters for each series', () => {
        const experiment = { ...experimentBase }
        const metric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.FUNNEL,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: 'event1',
                    name: 'event1',
                    properties: [
                        { key: 'bar', value: 'baz', operator: PropertyOperator.Exact, type: PropertyFilterType.Event },
                    ],
                },
                { kind: NodeKind.ActionsNode, id: 123, name: 'action1' },
            ],
        } satisfies ExperimentMetric

        const filters = getViewRecordingFilters(experiment, metric, 'variantA')
        expect(filters[1]).toEqual({
            id: 'event1',
            name: 'event1',
            type: 'events',
            properties: [
                { key: 'bar', value: 'baz', operator: PropertyOperator.Exact, type: PropertyFilterType.Event },
            ],
        })
        expect(filters[2]).toEqual({
            id: 123,
            name: 'action1',
            type: 'actions',
        })
    })
})

describe('getViewRecordingFiltersLegacy', () => {
    const featureFlagKey = 'jan-16-running'

    it('returns the correct filters for an experiment query', () => {
        const filters = getViewRecordingFiltersLegacy(
            EXPERIMENT_WITH_MEAN_METRIC.metrics[0] as ExperimentMetric,
            featureFlagKey,
            'control'
        )
        expect(filters).toEqual([
            {
                id: '$pageview',
                name: '$pageview',
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
        const filters = getViewRecordingFiltersLegacy(
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
        const filters = getViewRecordingFiltersLegacy(
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
        const filters = getViewRecordingFiltersLegacy(
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
        const filters = getViewRecordingFiltersLegacy(
            metricTrendActionJson as ExperimentTrendsQuery,
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
        user_access_level: AccessControlLevel.Admin,
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
                    query: {
                        kind: NodeKind.ExperimentTrendsQuery,
                        count_query: { kind: NodeKind.TrendsQuery, series: [] },
                    },
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

    it('returns false if shared metrics contain no legacy queries', () => {
        const experiment = {
            ...experimentJson,
            metrics: [],
            metrics_secondary: [],
            saved_metrics: [
                {
                    query: {
                        kind: NodeKind.ExperimentMetric,
                        metric_type: ExperimentMetricType.MEAN,
                        source: { kind: NodeKind.EventsNode, event: 'test' },
                    },
                },
            ],
        } as unknown as Experiment

        expect(isLegacyExperiment(experiment)).toBe(false)
    })
})
