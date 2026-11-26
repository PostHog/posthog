import { Counter } from 'prom-client'

import { HogFlow, getInternalEventFilterEventIds } from '~/cdp/schema/hogflow'

import { QuotaLimiting } from '../../../common/services/quota-limiting.service'
import { CyclotronJobInvocationHogFlow } from '../../types'
import { HogFunctionMonitoringService } from '../monitoring/hog-function-monitoring.service'
import { WorkflowsActivationReporter } from '../monitoring/workflows-activation-reporter'

export const counterHogFlowQuotaLimited = new Counter({
    name: 'cdp_hog_flow_quota_limited',
    help: 'A hog flow invocation was quota limited',
    labelNames: ['team_id'],
})

export const HOG_FLOW_QUOTA_LIMITED_MESSAGE = 'The project is over its workflow quota'

export interface HogFlowQuotaLimitResult {
    isLimited: boolean
}

// The step id of the email in a workflow the transactional send API made. The API refuses it in any other workflow, so
// the usage report and this check can tell a transactional send from a workflow email by it.
export const TRANSACTIONAL_EMAIL_ACTION_ID = 'transactional_email'

// Support replies and ticket updates must reach the customer, so the API lets these workflows keep transactional email.
// Keep in step with SUPPORT_EVENTS in products/workflows/backend/services/transactional_steps.py.
const SUPPORT_EVENTS = new Set([
    '$conversation_ticket_created',
    '$conversation_ticket_status_changed',
    '$conversation_ticket_priority_changed',
    '$conversation_ticket_assigned',
    '$conversation_ticket_tag_added',
    '$conversation_message_sent',
    '$conversation_private_message_sent',
    '$conversation_message_received',
])

function triggersOnlyOnSupportEvents(hogFlow: HogFlow): boolean {
    const trigger = hogFlow.trigger
    if (trigger.type === 'internal-event') {
        const eventIds = getInternalEventFilterEventIds(trigger.filters)
        return !!eventIds && eventIds.every((eventId) => SUPPORT_EVENTS.has(eventId))
    }
    if (trigger.type !== 'event') {
        return false
    }
    const events = trigger.filters?.events ?? []
    // The filter compiler checks the event name only on entries of type `events`, so an untyped entry can match events
    // with any name.
    return (
        events.length > 0 &&
        !trigger.filters?.actions?.length &&
        events.every((event) => event?.type === 'events' && SUPPORT_EVENTS.has(event?.id))
    )
}

// Transactional emails bypass the email quota. Each send still reports billable usage, so the team pays for it.
function sendsOnlyTransactionalEmail(hogFlow: HogFlow): boolean {
    const emailActions = hogFlow.actions.filter((action) => action.type === 'function_email')
    if (emailActions.length === 0) {
        return false
    }
    if (emailActions.every((action) => action.id === TRANSACTIONAL_EMAIL_ACTION_ID)) {
        return true
    }
    return (
        triggersOnlyOnSupportEvents(hogFlow) &&
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
    workflowsActivationReporter: Pick<WorkflowsActivationReporter, 'report'>
}

function sendsEmail(hogFlow: HogFlow): boolean {
    return Array.isArray(hogFlow.billable_action_types) && hogFlow.billable_action_types.includes('function_email')
}

/**
 * Checks if a hog flow invocation should be quota limited and handles the appropriate metrics.
 * Returns true if the invocation should be blocked, false otherwise.
 */
export async function shouldBlockHogFlowDueToQuota(
    item: Pick<CyclotronJobInvocationHogFlow, 'teamId' | 'functionId' | 'hogFlow'>,
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
        if (sendsEmail(item.hogFlow)) {
            void context.workflowsActivationReporter.report(item.teamId, 'workflows send blocked', {
                reason: 'quota_limited',
                channel: 'email',
                workflow_id: item.functionId,
            })
        }
        return true
    }

    return false
}
