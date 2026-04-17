import { DateTime } from 'luxon'

import { HogFlowAction } from '~/schema/hogflow'

import { findContinueAction, findNextAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'
import { calculatedScheduledAt } from './delay'

type WaitUntilEventAction = Extract<HogFlowAction, { type: 'wait_until_event' }>

/**
 * Handler for `wait_until_event`. Parks the job until either:
 *   1. The subscription matcher consumer wakes it because a matching event arrived, or
 *   2. The `max_wait_duration` timeout fires.
 *
 * The consumer handles all event matching externally by scanning parked hogflow
 * jobs and evaluating the step's filters against incoming events. This handler
 * only parks and determines which branch to take on re-entry.
 *
 * On re-entry, `waitingForEvent` on `currentAction` tells us this is a resume
 * (not a first visit). The consumer sets `eventMatched` when it wakes the job
 * via a match; absence means the scheduled timeout fired.
 */
export class WaitUntilEventHandler implements ActionHandler {
    execute({ invocation, action, result }: ActionHandlerOptions<WaitUntilEventAction>): ActionHandlerResult {
        const isReentry = invocation.state?.currentAction?.waitingForEvent === true

        if (!isReentry) {
            return this.park(invocation, action, result)
        }

        if (invocation.state?.currentAction) {
            invocation.state.currentAction.waitingForEvent = false
        }

        const eventMatched = invocation.state?.currentAction?.eventMatched === true

        if (eventMatched) {
            result.logs.push({
                level: 'info',
                timestamp: DateTime.now(),
                message: `Matching event arrived - taking the matched path`,
            })
            return { nextAction: findNextAction(invocation.hogFlow, action.id, 0) }
        }

        result.logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Timed out waiting for event - taking the timeout path`,
        })
        return { nextAction: findContinueAction(invocation) }
    }

    private park(
        invocation: ActionHandlerOptions<WaitUntilEventAction>['invocation'],
        action: WaitUntilEventAction,
        result: ActionHandlerOptions<WaitUntilEventAction>['result']
    ): ActionHandlerResult {
        const expiresAt = calculatedScheduledAt(
            action.config.max_wait_duration,
            invocation.state?.currentAction?.startedAtTimestamp
        )

        if (!expiresAt) {
            return { nextAction: findContinueAction(invocation) }
        }

        if (invocation.state?.currentAction) {
            invocation.state.currentAction.waitingForEvent = true
        }

        const eventNames = action.config.events
            .flatMap((e) => extractEventNames(e.filters))
            .filter(Boolean)
            .join(', ')

        result.logs.push({
            level: 'info',
            timestamp: DateTime.now(),
            message: `Waiting for event: ${eventNames || '(any)'} (timeout: ${expiresAt.toUTC().toISO()})`,
        })

        return { scheduledAt: expiresAt }
    }
}

function extractEventNames(filters: any): string[] {
    if (!filters || typeof filters !== 'object') {
        return []
    }
    const events = filters.events
    if (!Array.isArray(events) || events.length === 0) {
        return []
    }
    return events
        .map((e: any) => (e && typeof e === 'object' ? (e.id ?? e.name ?? '') : ''))
        .filter((name: string) => name !== '')
}
