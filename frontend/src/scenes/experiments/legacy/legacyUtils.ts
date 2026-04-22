import { ExperimentTrendsQuery, ExperimentFunnelsQuery, NodeKind } from '~/queries/schema/schema-general'
import { InsightType } from '~/types'

/**
 * @deprecated
 * Use the getInsightType function from the experimentLogic instead.
 */
export const getInsightType = (metric: ExperimentTrendsQuery | ExperimentFunnelsQuery): InsightType => {
    return metric.kind === NodeKind.ExperimentTrendsQuery ? InsightType.TRENDS : InsightType.FUNNELS
}
