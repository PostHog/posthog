import { InsightShortId } from '~/types'

// :TRICKY: `new-` prefix indicates an unsaved insight and slightly alters
// behaviour of insight related logics
export const EXPERIMENT_INSIGHT_ID = 'new-experiment-insight' as InsightShortId
export const SEONDARY_METRIC_INSIGHT_ID = 'new-secondary-metric-insight' as InsightShortId
