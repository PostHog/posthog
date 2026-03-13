import { Counter } from 'prom-client'

import { QuotaLimiting } from '../../../common/services/quota-limiting.service'
import { HogFlow, HogFlowAction } from '../../../schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '../../types'
import { HogFunctionTemplateManagerService } from '../managers/hog-function-template-manager.service'
import { HogFunctionMonitoringService } from '../monitoring/hog-function-monitoring.service'

export const counterHogFlowQuotaLimited = new Counter({
    name: 'cdp_hog_flow_quota_limited',
    help: 'A hog flow invocation was quota limited',
    labelNames: ['team_id'],
})

const BILLABLE_ACTION_TYPES = new Set(['function', 'function_email', 'function_sms', 'function_push'])

export interface HogFlowQuotaLimitResult {
    isLimited: boolean
}

/**
 * Computes the set of billable action types for a hogflow by checking each action's
 * template `free` flag. Actions with `free: true` templates are excluded.
 * Actions without a template_id default to billable.
 */
async function computeBillableActionTypes(
    hogFlow: HogFlow,
    hogFunctionTemplateManager: HogFunctionTemplateManagerService
): Promise<Set<string>> {
    // Filter to actions with billable types that have a config with template_id
    const candidateActions = hogFlow.actions.filter(
        (a): a is HogFlowAction & { config: { template_id: string } } =>
            BILLABLE_ACTION_TYPES.has(a.type) && 'config' in a && 'template_id' in a.config
    )

    // Actions with billable types but no template_id are always billable
    const actionsWithoutTemplate = hogFlow.actions.filter(
        (a) => BILLABLE_ACTION_TYPES.has(a.type) && !('config' in a && 'template_id' in a.config)
    )

    const billableTypes = new Set(actionsWithoutTemplate.map((a) => a.type))

    if (candidateActions.length === 0) {
        return billableTypes
    }

    // Resolve templates to check free status
    const templateIds = [...new Set(candidateActions.map((a) => a.config.template_id))]
    const templates = await hogFunctionTemplateManager.getHogFunctionTemplates(templateIds)

    for (const action of candidateActions) {
        const template = templates[action.config.template_id]
        // If template not found or not free, the action is billable
        if (!template || !template.free) {
            billableTypes.add(action.type)
        }
    }

    return billableTypes
}

/**
 * Checks if a hogflow is quota limited based on its billable action types.
 * Dynamically computes billable types by checking template `free` flags.
 */
export async function checkHogFlowQuotaLimits(
    hogFlow: HogFlow,
    teamId: number,
    quotaLimiting: QuotaLimiting,
    hogFunctionTemplateManager: HogFunctionTemplateManagerService
): Promise<HogFlowQuotaLimitResult> {
    const billableActionTypes = await computeBillableActionTypes(hogFlow, hogFunctionTemplateManager)

    // If no billable action types, no need to check quotas
    if (billableActionTypes.size === 0) {
        return { isLimited: false }
    }

    // Check which quotas the team is limited on
    const [isEmailQuotaLimited, isDestinationQuotaLimited] = await Promise.all([
        quotaLimiting.isTeamQuotaLimited(teamId, 'workflow_emails'),
        quotaLimiting.isTeamQuotaLimited(teamId, 'workflow_destinations_dispatched'),
    ])

    // Check if any billable action type is quota limited
    if (isEmailQuotaLimited && billableActionTypes.has('function_email')) {
        return { isLimited: true }
    }

    if (isDestinationQuotaLimited && billableActionTypes.has('function')) {
        return { isLimited: true }
    }

    return { isLimited: false }
}

export interface HogFlowQuotaLimitingContext {
    quotaLimiting: QuotaLimiting
    hogFunctionMonitoringService: HogFunctionMonitoringService
    hogFunctionTemplateManager: HogFunctionTemplateManagerService
}

/**
 * Checks if a hog flow invocation should be quota limited and handles the appropriate metrics.
 * Returns true if the invocation should be blocked, false otherwise.
 */
export async function shouldBlockHogFlowDueToQuota(
    item: CyclotronJobInvocationHogFlow,
    context: HogFlowQuotaLimitingContext
): Promise<boolean> {
    const quotaLimitResult = await checkHogFlowQuotaLimits(
        item.hogFlow,
        item.teamId,
        context.quotaLimiting,
        context.hogFunctionTemplateManager
    )

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
