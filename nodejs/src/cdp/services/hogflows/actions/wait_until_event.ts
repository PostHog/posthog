import { DateTime } from 'luxon'

import { HogFlowAction } from '~/schema/hogflow'

import { logger } from '../../../../utils/logger'
import { EventSubscriptionsService } from '../event-subscriptions.service'
import { findContinueAction, findNextAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'
import { calculatedScheduledAt } from './delay'

type WaitUntilEventAction = Extract<HogFlowAction, { type: 'wait_until_event' }>

/**
 * Handler for `wait_until_event`. Push-based: when the workflow reaches this
 * step the handler creates one subscription row per configured event in
 * `cyclotron_event_subscriptions` and parks the job until either:
 *   1. The cdp-events consumer wakes it because a matching event arrived, or
 *   2. The `max_wait_duration` timeout fires.
 *
 * On the second invocation (after wake or timeout), the handler distinguishes
 * the two paths by checking whether the subscriptions for this job still exist:
 *   - No subscriptions left -> consumer wiped them on a match -> branch edge.
 *   - Subscriptions still present -> timeout fired -> continue edge.
 *
 * The `waitingForEvent` flag on `currentAction` distinguishes the first visit
 * (subscriptions don't exist yet because we haven't created them) from a
 * post-match re-entry (subscriptions don't exist because the consumer deleted them).
 */
export class WaitUntilEventHandler implements ActionHandler {
    constructor(private subscriptions: EventSubscriptionsService | null) {}

    async execute({
        invocation,
        action,
        result,
    }: ActionHandlerOptions<WaitUntilEventAction>): Promise<ActionHandlerResult> {
        if (!this.subscriptions) {
            logger.warn(
                'WaitUntilEventHandler: subscriptions service not configured, falling through to continue edge',
                { actionId: action.id }
            )
            return { nextAction: findContinueAction(invocation) }
        }

        const personId = invocation.state?.personId ?? invocation.person?.id
        if (!personId) {
            logger.warn('WaitUntilEventHandler: no personId on invocation, falling through', {
                actionId: action.id,
                invocationId: invocation.id,
            })
            return { nextAction: findContinueAction(invocation) }
        }

        const isReentry = invocation.state?.currentAction?.waitingForEvent === true

        // First visit: create subscriptions, mark as waiting, schedule the timeout.
        if (!isReentry) {
            return this.createAndPark(invocation, action, String(personId), result)
        }

        // Re-entry: figure out which path was taken by checking the subscriptions table.
        const remaining = await this.subscriptions.getForJob(invocation.id)

        // Clear the waiting flag so the next action sees a clean state.
        if (invocation.state?.currentAction) {
            invocation.state.currentAction.waitingForEvent = false
        }

        if (remaining.length === 0) {
            // Consumer wiped them on a match -> branch edge (index 0 = "matched" path).
            result.logs.push({
                level: 'info',
                timestamp: DateTime.now(),
                message: `Event matched - taking the matched path`,
            })
            return { nextAction: findNextAction(invocation.hogFlow, action.id, 0) }
        }

        // Subscriptions still present -> timeout fired -> continue edge (= "no match" path).
        const eventNames = remaining.map((s) => s.eventName).join(', ')
        result.logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Timed out waiting for event${remaining.length > 1 ? 's' : ''} (${eventNames}) - taking the timeout path`,
        })
        await this.subscriptions.deleteForJob(invocation.id)
        return { nextAction: findContinueAction(invocation) }
    }

    private async createAndPark(
        invocation: ActionHandlerOptions<WaitUntilEventAction>['invocation'],
        action: WaitUntilEventAction,
        personId: string,
        result: ActionHandlerOptions<WaitUntilEventAction>['result']
    ): Promise<ActionHandlerResult> {
        const expiresAt = calculatedScheduledAt(
            action.config.max_wait_duration,
            invocation.state?.currentAction?.startedAtTimestamp
        )

        if (!expiresAt) {
            return { nextAction: findContinueAction(invocation) }
        }

        const subs = action.config.events.map((eventConfig) => {
            const eventName = extractEventName(eventConfig.filters)
            const bytecode = extractBytecode(eventConfig.filters)
            return {
                jobId: invocation.id,
                teamId: invocation.teamId,
                personId,
                eventName: eventName ?? '',
                filters: eventConfig.filters ?? null,
                bytecode,
                expiresAt: expiresAt.toJSDate(),
            }
        })

        await this.subscriptions!.createMany(subs)

        // Mark as waiting so the next handler invocation knows this is a re-entry.
        if (invocation.state?.currentAction) {
            invocation.state.currentAction.waitingForEvent = true
        }

        const eventNames = subs
            .map((s) => s.eventName)
            .filter(Boolean)
            .join(', ')
        result.logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Waiting for event${subs.length > 1 ? 's' : ''}: ${eventNames || '(any)'} (timeout: ${expiresAt.toUTC().toISO()})`,
        })

        return { scheduledAt: expiresAt }
    }
}

/**
 * Extract the event name from the action filters config. The filters shape is
 * the standard PostHog filter envelope (`{ events: [{ id, name, type }, ...] }`).
 */
function extractEventName(filters: any): string | null {
    if (!filters || typeof filters !== 'object') {
        return null
    }
    const events = filters.events
    if (!Array.isArray(events) || events.length === 0) {
        return null
    }
    const first = events[0]
    if (!first || typeof first !== 'object') {
        return null
    }
    return first.id ?? first.name ?? null
}

/**
 * Extract the compiled bytecode from a filters dict. The Django HogFlow
 * serializer compiles filters via `HogFunctionFiltersSerializer`, which
 * stores the result at `filters.bytecode`.
 */
function extractBytecode(filters: any): any[] | null {
    if (!filters || typeof filters !== 'object') {
        return null
    }
    const bytecode = filters.bytecode
    return Array.isArray(bytecode) && bytecode.length > 0 ? bytecode : null
}
