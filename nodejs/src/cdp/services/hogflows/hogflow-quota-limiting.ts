import { Counter } from 'prom-client'

import { HogFlow, HogFlowAction } from '~/cdp/schema/hogflow'

import { QuotaLimiting } from '../../../common/services/quota-limiting.service'
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

// Transactional emails bypass the email quota. Each send still reports billable usage, so the team pays for it.
function sendsOnlyTransactionalEmail(hogFlow: HogFlow): boolean {
    const emailActions = hogFlow.actions.filter(
        (action): action is Extract<HogFlowAction, { type: 'function_email' }> => action.type === 'function_email'
    )
    return (
        emailActions.length > 0 &&
        emailActions.every((action) => action.config?.message_category_type === 'transactional')
    )
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
    if (
        isEmailQuotaLimited &&
        billableActionTypes.includes('function_email') &&
        !sendsOnlyTransactionalEmail(hogFlow)
    ) {
        return { isLimited: true }
    }

    // Push sends bill as destinations for now, so they fall under the destination quota
    if (
        isDestinationQuotaLimited &&
        (billableActionTypes.includes('function') || billableActionTypes.includes('function_push'))
    ) {
        return { isLimited: true }
    }

    return { isLimited: false }
}

export interface HogFlowQuotaLimitingContext {
    quotaLimiting: QuotaLimiting
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
    const quotaLimitResult = await checkHogFlowQuotaLimits(item.hogFlow, item.teamId, context.quotaLimiting)

    if (quotaLimitResult.isLimited) {
        counterHogFlowQuotaLimited.labels({ team_id: item.teamId }).inc()

        context.hogFunctionMonitoringService.queueAppMetric(
            {
                team_id: item.teamId,
                app_source_id: item.functionId,
                metric_kind: 'failure',
                metric_name: 'quota_limited',
                count: 1,
                app_source_version: { id: item.hogFlow.id, version: item.hogFlow.version },
            },
            'hog_flow'
        )
        return true
    }

    return false
}
