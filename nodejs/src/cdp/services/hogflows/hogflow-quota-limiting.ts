import { Counter } from 'prom-client'

import { QuotaLimiting } from '../../../common/services/quota-limiting.service'
import { HogFlow } from '../../../schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '../../types'
import { HogFunctionMonitoringService } from '../monitoring/hog-function-monitoring.service'

export const counterHogFlowQuotaLimited = new Counter({
    name: 'cdp_hog_flow_quota_limited',
    help: 'A hog flow invocation was quota limited',
    labelNames: ['team_id'],
})

export interface HogFlowQuotaLimitResult {
    isLimited: boolean
}

/**
 * Checks if a hogflow is quota limited based on its billable action types.
 * Uses the pre-computed billable_action_types field for efficient quota checking.
 */
export async function checkHogFlowQuotaLimits(
    hogFlow: HogFlow,
    teamId: number,
    quotaLimiting: QuotaLimiting
): Promise<HogFlowQuotaLimitResult> {
    // Ensure billable_action_types is an array (handle null, undefined, or non-array values)
    const billableActionTypes = Array.isArray(hogFlow.billable_action_types) ? hogFlow.billable_action_types : []

    // If no billable action types, no need to check quotas
    if (billableActionTypes.length === 0) {
        return { isLimited: false }
    }

    // Check which quotas the team is limited on
    const [isEmailQuotaLimited, isDestinationQuotaLimited] = await Promise.all([
        quotaLimiting.isTeamQuotaLimited(teamId, 'workflow_emails'),
        quotaLimiting.isTeamQuotaLimited(teamId, 'workflow_destinations_dispatched'),
    ])

    // Check if any billable action type is quota limited
    if (isEmailQuotaLimited && billableActionTypes.includes('function_email')) {
        return { isLimited: true }
    }

    if (isDestinationQuotaLimited && billableActionTypes.includes('function')) {
        return { isLimited: true }
    }

    return { isLimited: false }
}

export interface HogFlowQuotaLimitingContext {
    hub: {
        quotaLimiting: QuotaLimiting
    }
    hogFunctionMonitoringService: HogFunctionMonitoringService
}

/**
 * Checks if a hog flow invocation should be quota limited and handles the appropriate metrics.
 * Returns true if the invocation should be blocked, false otherwise.
 */
export async function shouldBlockHogFlowDueToQuota(
    item: CyclotronJobInvocationHogFlow,
    context: HogFlowQuotaLimitingContext
): Promise<boolean> {
    const quotaLimitResult = await checkHogFlowQuotaLimits(item.hogFlow, item.teamId, context.hub.quotaLimiting)

    if (quotaLimitResult.isLimited) {
        counterHogFlowQuotaLimited.labels({ team_id: item.teamId }).inc()

        context.hogFunctionMonitoringService.queueAppMetric(
            {
                team_id: item.teamId,
                app_source_id: item.functionId,
                metric_kind: 'failure',
                metric_name: 'quota_limited',
                count: 1,
            },
            'hog_flow'
        )
        return true
    }

    return false
}
