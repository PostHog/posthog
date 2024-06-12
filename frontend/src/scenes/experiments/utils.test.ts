import { EntityType, InsightType } from '~/types'

import { getMinimumDetectableEffect } from './utils'

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
})
