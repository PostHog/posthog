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
 *   1. The subscription matcher consumer wakes it because a matching event arrived, or
 *   2. The `max_wait_duration` timeout fires.
 *
 * On re-entry (after wake or timeout), the handler distinguishes the two paths
 * by the presence of wait_step subscriptions for this job:
 *   - No subs left -> the consumer deleted them on a match -> matched branch.
 *   - Subs still present -> scheduled timeout fired -> continue edge.
 *
 * A `waitingForEvent` flag on `currentAction` distinguishes the first visit
 * (no subs yet because we have not created them) from a post-match re-entry
 * (no subs because the consumer deleted them).
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

        if (!isReentry) {
            return this.createAndPark(invocation, action, String(personId), result)
        }

        const remaining = await this.subscriptions.getForJob(invocation.id, 'wait_step')

        if (invocation.state?.currentAction) {
            invocation.state.currentAction.waitingForEvent = false
        }

        if (remaining.length === 0) {
            result.logs.push({
                level: 'info',
                timestamp: DateTime.now(),
                message: `Matching event arrived - taking the matched path`,
            })
            return { nextAction: findNextAction(invocation.hogFlow, action.id, 0) }
        }

        const eventNames = remaining.map((s) => s.eventName).join(', ')
        result.logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Timed out waiting for event${remaining.length > 1 ? 's' : ''} (${eventNames}) - taking the timeout path`,
        })
        await this.subscriptions.deleteForJob(invocation.id, 'wait_step')
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

        // Each config entry can have multiple events in its filters (OR within
        // the ActionFilter UI). Create one subscription row per event name so
        // the DB lookup by (team_id, event_name, person_id) can match any of them.
        const subs = action.config.events.flatMap((eventConfig) => {
            const eventNames = extractEventNames(eventConfig.filters)
            const bytecode = extractBytecode(eventConfig.filters)
            return eventNames.map((eventName) => ({
                jobId: invocation.id,
                teamId: invocation.teamId,
                personId,
                eventName,
                filters: eventConfig.filters ?? null,
                bytecode,
                expiresAt: expiresAt.toJSDate(),
            }))
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
 * Extract ALL event names from the action filters config. The filters shape is
 * the standard PostHog filter envelope (`{ events: [{ id, name, type }, ...] }`).
 * A single filter entry can contain multiple events (OR logic within the ActionFilter UI).
 */
function extractEventNames(filters: any): string[] {
    if (!filters || typeof filters !== 'object') {
        return ['']
    }
    const events = filters.events
    if (!Array.isArray(events) || events.length === 0) {
        return ['']
    }
    const names = events
        .map((e: any) => (e && typeof e === 'object' ? (e.id ?? e.name ?? '') : ''))
        .filter((name: string) => name !== '')
    return names.length > 0 ? names : ['']
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
