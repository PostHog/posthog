import { CyclotronJobInvocationResult } from '~/cdp/types'

type HogFlowBillingMetric = {
    teamId: number
    functionId: string
    invocationId: string
} & (
    | {
          metricKind: 'billing'
          metricName: 'billable_invocation'
      }
    | { metricKind: 'email'; metricName: 'email_sent' | 'email_failed' }
)

/**
 * In workflows, we bill per-function-invocation so that pricing is equivalent to Hog Functions.
 *
 * For certain native functions like email sending, we instead bill per email sent as these
 * have a slight upcharge associated with them.
 */
export const recordHogFlowBillableInvocation = (result: CyclotronJobInvocationResult, metric: HogFlowBillingMetric) => {
    result.metrics.push({
        team_id: metric.teamId,
        app_source_id: metric.functionId,
        instance_id: metric.invocationId,
        metric_name: metric.metricName,
        metric_kind: metric.metricKind,
        count: 1,
    })
}
