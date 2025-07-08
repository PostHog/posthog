import { HogFlowAction } from '../../../schema/hogflow'
import { CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '../../types'

export class HogFlowMetricsService {
    trackActionMetric(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>,
        action: HogFlowAction,
        metricName: 'failed' | 'succeeded' | 'filtered'
    ): void {
        result.metrics.push({
            team_id: result.invocation.hogFlow.team_id,
            app_source_id: result.invocation.hogFlow.id,
            instance_id: action.id,
            metric_kind: metricName === 'failed' ? 'failure' : metricName === 'succeeded' ? 'success' : 'other',
            metric_name: metricName,
            count: 1,
        })
    }
}
