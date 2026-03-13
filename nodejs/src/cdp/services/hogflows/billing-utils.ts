import { CyclotronJobInvocation, CyclotronJobInvocationResult } from '~/cdp/types'

type HogFlowBillingMetricData = {
    invocation: CyclotronJobInvocation
    billingMetricType: 'fetch' | 'email' | 'sms' | 'push'
}

/**
 * In workflows, we bill per-function-invocation so that pricing is equivalent to Hog Functions.
 *
 * For certain native functions like email sending, we instead bill per email sent as these
 * have a slight upcharge associated with them.
 */
export const trackHogFlowBillableInvocation = (
    result: CyclotronJobInvocationResult,
    data: HogFlowBillingMetricData
) => {
    result.metrics.push({
        team_id: data.invocation.teamId,
        app_source_id: data.invocation.functionId,
        instance_id: data.invocation.id,
        metric_kind: data.billingMetricType,
        metric_name: 'billable_invocation',
        count: 1,
    })
}
