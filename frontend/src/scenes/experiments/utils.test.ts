import EXPERIMENT_V3_WITH_ONE_EXPERIMENT_QUERY from '~/mocks/fixtures/api/experiments/_experiment_v3_with_one_metric.json'
import metricFunnelEventsJson from '~/mocks/fixtures/api/experiments/_metric_funnel_events.json'
import metricTrendActionJson from '~/mocks/fixtures/api/experiments/_metric_trend_action.json'
import metricTrendCustomExposureJson from '~/mocks/fixtures/api/experiments/_metric_trend_custom_exposure.json'
import metricTrendFeatureFlagCalledJson from '~/mocks/fixtures/api/experiments/_metric_trend_feature_flag_called.json'
import { ExperimentFunnelsQuery, ExperimentQuery, ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import {
    EntityType,
    FeatureFlagFilters,
    FeatureFlagType,
    InsightType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

import { getNiceTickValues } from './MetricsView/MetricsView'
import {
    featureFlagEligibleForExperiment,
    getMinimumDetectableEffect,
    getViewRecordingFilters,
    transformFiltersForWinningVariant,
} from './utils'

describe('utils', () => {
    it('Funnel experiment returns correct MDE', async () => {
        const metricType = InsightType.FUNNELS
        const trendResults = [
            {
                action: {
                    id: '$pageview',
                    type: 'events' as EntityType,
                    order: 0,
                    name: '$pageview',
                    custom_name: null,
                    math: 'total',
                    math_group_type_index: null,
                },
                aggregated_value: 0,
                label: '$pageview',
                count: 0,
                data: [],
                labels: [],
                days: [],
            },
        ]

        let conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0 }
        expect(getMinimumDetectableEffect(metricType, conversionMetrics, trendResults)).toEqual(1)
        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 1 }
        expect(getMinimumDetectableEffect(metricType, conversionMetrics, trendResults)).toEqual(1)

        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.01 }
        expect(getMinimumDetectableEffect(metricType, conversionMetrics, trendResults)).toEqual(1)
        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.99 }
        expect(getMinimumDetectableEffect(metricType, conversionMetrics, trendResults)).toEqual(1)

        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.1 }
        expect(getMinimumDetectableEffect(metricType, conversionMetrics, trendResults)).toEqual(5)
        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.9 }
        expect(getMinimumDetectableEffect(metricType, conversionMetrics, trendResults)).toEqual(5)

        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.3 }
        expect(getMinimumDetectableEffect(metricType, conversionMetrics, trendResults)).toEqual(3)
        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.7 }
        expect(getMinimumDetectableEffect(metricType, conversionMetrics, trendResults)).toEqual(3)

        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.2 }
        expect(getMinimumDetectableEffect(metricType, conversionMetrics, trendResults)).toEqual(4)
        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.8 }
        expect(getMinimumDetectableEffect(metricType, conversionMetrics, trendResults)).toEqual(4)

        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.5 }
        expect(getMinimumDetectableEffect(metricType, conversionMetrics, trendResults)).toEqual(5)
    })

    it('Trend experiment returns correct MDE', async () => {
        const metricType = InsightType.TRENDS
        const conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0 }
        const trendResults = [
            {
                action: {
                    id: '$pageview',
                    type: 'events' as EntityType,
                    order: 0,
                    name: '$pageview',
                    custom_name: null,
                    math: 'total',
                    math_group_type_index: null,
                },
                aggregated_value: 0,
                label: '$pageview',
                count: 0,
                data: [],
                labels: [],
                days: [],
            },
        ]

        trendResults[0].count = 0
        expect(getMinimumDetectableEffect(metricType, conversionMetrics, trendResults)).toEqual(100)

        trendResults[0].count = 200
        expect(getMinimumDetectableEffect(metricType, conversionMetrics, trendResults)).toEqual(100)

        trendResults[0].count = 201
        expect(getMinimumDetectableEffect(metricType, conversionMetrics, trendResults)).toEqual(20)

        trendResults[0].count = 1001
        expect(getMinimumDetectableEffect(metricType, conversionMetrics, trendResults)).toEqual(5)

        trendResults[0].count = 20000
        expect(getMinimumDetectableEffect(metricType, conversionMetrics, trendResults)).toEqual(5)
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
            EXPERIMENT_V3_WITH_ONE_EXPERIMENT_QUERY.metrics[0] as ExperimentQuery,
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
    it('throws an error for a feature flag that already has an experiment set', () => {
        const featureFlag = {
            ...baseFeatureFlag,
            experiment_set: [2],
        }
        expect(() => featureFlagEligibleForExperiment(featureFlag)).toThrow(
            'Feature flag is already associated with an experiment.'
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
