import { QuotaLimiting } from '../../../common/services/quota-limiting.service'
import { HogFlow } from '../../../schema/hogflow'

export interface HogFlowQuotaLimitResult {
    isLimited: boolean
    limitedBy?: 'workflow_emails' | 'workflow_destinations_dispatched'
}

/**
 * Checks if a hogflow is quota limited based on its action types.
 * Efficiently checks quota limits first, then iterates through actions once
 * and breaks early when finding a limited action type.
 */
export async function checkHogFlowQuotaLimits(
    hogFlow: HogFlow,
    teamId: number,
    quotaLimiting: QuotaLimiting
): Promise<HogFlowQuotaLimitResult> {
    // First check which quotas the team is limited on
    const [isEmailQuotaLimited, isDestinationQuotaLimited] = await Promise.all([
        quotaLimiting.isTeamQuotaLimited(teamId, 'workflow_emails' as any),
        quotaLimiting.isTeamQuotaLimited(teamId, 'workflow_destinations_dispatched' as any),
    ])

    // Only check actions if team has quota limits
    if (isEmailQuotaLimited || isDestinationQuotaLimited) {
        // Iterate through actions once and break early when we find a limited type
        for (const action of hogFlow.actions) {
            if (isEmailQuotaLimited && action.type === 'function_email') {
                return {
                    isLimited: true,
                    limitedBy: 'workflow_emails',
                }
            }
            if (isDestinationQuotaLimited && action.type === 'function') {
                return {
                    isLimited: true,
                    limitedBy: 'workflow_destinations_dispatched',
                }
            }
        }
    }

    return {
        isLimited: false,
    }
}
