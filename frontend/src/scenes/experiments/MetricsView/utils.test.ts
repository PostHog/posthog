import type { ExperimentFunnelsQuery, ExperimentMetric, ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { ExperimentMetricMathType } from '~/types'

import { getDefaultMetricTitle, getMetricTag } from './utils'

describe('getMetricTag', () => {
    it('handles different metric types correctly', () => {
        const experimentMetric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            metric_config: {
                kind: NodeKind.ExperimentEventMetricConfig,
                math: ExperimentMetricMathType.TotalCount,
                event: 'purchase',
            },
        }

        const funnelMetric: ExperimentFunnelsQuery = {
            kind: NodeKind.ExperimentFunnelsQuery,
            funnels_query: {
                kind: NodeKind.FunnelsQuery,
                series: [],
            },
        }

        const trendMetric: ExperimentTrendsQuery = {
            kind: NodeKind.ExperimentTrendsQuery,
            count_query: {
                kind: NodeKind.TrendsQuery,
                series: [],
            },
        }

        expect(getMetricTag(experimentMetric)).toBe('Mean')
        expect(getMetricTag(funnelMetric)).toBe('Funnel')
        expect(getMetricTag(trendMetric)).toBe('Trend')
    })
})

describe('getDefaultMetricTitle', () => {
    it('handles ExperimentEventMetricConfig with math and math_property', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            metric_config: {
                kind: NodeKind.ExperimentEventMetricConfig,
                event: 'purchase completed',
            },
        }
        expect(getDefaultMetricTitle(metric)).toBe('purchase completed')
    })

    it('returns action name for ExperimentActionMetricConfig', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            metric_config: {
                kind: NodeKind.ExperimentActionMetricConfig,
                action: 1,
                name: 'purchase',
            },
        }

        expect(getDefaultMetricTitle(metric)).toBe('purchase')
    })
})
