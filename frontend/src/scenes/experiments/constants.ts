import { InsightShortId } from '~/types'

// :TRICKY: `new-` prefix indicates an unsaved insight and slightly alters
// behaviour of insight related logics
export const SECONDARY_METRIC_INSIGHT_ID = 'new-secondary-metric-insight' as InsightShortId

export enum MetricInsightId {
    Trends = 'new-experiment-trends-metric',
    TrendsExposure = 'new-experiment-trends-exposure',
    Funnels = 'new-experiment-funnels-metric',
    SecondaryTrends = 'new-experiment-secondary-trends',
    SecondaryFunnels = 'new-experiment-secondary-funnels',
}
