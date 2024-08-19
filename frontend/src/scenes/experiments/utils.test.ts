import { EntityType, FeatureFlagFilters, InsightType } from '~/types'

import { getMinimumDetectableEffect, transformFiltersForWinningVariant } from './utils'

describe('utils', () => {
    it('Funnel experiment returns correct MDE', async () => {
        const experimentInsightType = InsightType.FUNNELS
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
        expect(getMinimumDetectableEffect(experimentInsightType, conversionMetrics, trendResults)).toEqual(1)
        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 1 }
        expect(getMinimumDetectableEffect(experimentInsightType, conversionMetrics, trendResults)).toEqual(1)

        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.01 }
        expect(getMinimumDetectableEffect(experimentInsightType, conversionMetrics, trendResults)).toEqual(1)
        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.99 }
        expect(getMinimumDetectableEffect(experimentInsightType, conversionMetrics, trendResults)).toEqual(1)

        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.1 }
        expect(getMinimumDetectableEffect(experimentInsightType, conversionMetrics, trendResults)).toEqual(5)
        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.9 }
        expect(getMinimumDetectableEffect(experimentInsightType, conversionMetrics, trendResults)).toEqual(5)

        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.3 }
        expect(getMinimumDetectableEffect(experimentInsightType, conversionMetrics, trendResults)).toEqual(3)
        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.7 }
        expect(getMinimumDetectableEffect(experimentInsightType, conversionMetrics, trendResults)).toEqual(3)

        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.2 }
        expect(getMinimumDetectableEffect(experimentInsightType, conversionMetrics, trendResults)).toEqual(4)
        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.8 }
        expect(getMinimumDetectableEffect(experimentInsightType, conversionMetrics, trendResults)).toEqual(4)

        conversionMetrics = { averageTime: 0, stepRate: 0, totalRate: 0.5 }
        expect(getMinimumDetectableEffect(experimentInsightType, conversionMetrics, trendResults)).toEqual(5)
    })

    it('Trend experiment returns correct MDE', async () => {
        const experimentInsightType = InsightType.TRENDS
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
        expect(getMinimumDetectableEffect(experimentInsightType, conversionMetrics, trendResults)).toEqual(100)

        trendResults[0].count = 200
        expect(getMinimumDetectableEffect(experimentInsightType, conversionMetrics, trendResults)).toEqual(100)

        trendResults[0].count = 201
        expect(getMinimumDetectableEffect(experimentInsightType, conversionMetrics, trendResults)).toEqual(20)

        trendResults[0].count = 1001
        expect(getMinimumDetectableEffect(experimentInsightType, conversionMetrics, trendResults)).toEqual(5)

        trendResults[0].count = 20000
        expect(getMinimumDetectableEffect(experimentInsightType, conversionMetrics, trendResults)).toEqual(5)
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
