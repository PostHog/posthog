import { DateTime } from 'luxon'

import { HogFlowAction } from '~/schema/hogflow'

import { logger } from '../../../../utils/logger'
import { filterFunctionInstrumented } from '../../../utils/hog-function-filtering'
import { EventSubscriptionsService } from '../event-subscriptions.service'
import { findContinueAction, findNextAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'
import { calculatedScheduledAt } from './delay'

type WaitUntilConditionAction = Extract<HogFlowAction, { type: 'wait_until_condition' }>

// Max time between polls when waiting for a person property condition.
const DEFAULT_POLL_INTERVAL_SECONDS = 10 * 60

/**
 * Handler for `wait_until_condition`. This step pauses a workflow until any of:
 *   1. A configured person property condition matches (pull-based polling), OR
 *   2. A configured event fires for the person (push-based subscription), OR
 *   3. The `max_wait_duration` timeout elapses.
 *
 * Users can configure property conditions, event subscriptions, or both. Any
 * match takes the "matched" branch edge. Timeout takes the "no match" continue edge.
 *
 * Execution:
 * - First visit: if events are configured, create subscription rows and set the
 *   `waitingForEvent` flag. Evaluate the condition (it might already match).
 *   Park the job with a scheduledAt that's the min of (next poll, timeout).
 * - Re-entry (after wake or poll): check for matched event subscriptions, re-evaluate
 *   the condition, check for timeout. Any hit takes the matched path; otherwise park again.
 */
export class WaitUntilConditionHandler implements ActionHandler {
    constructor(private subscriptions: EventSubscriptionsService | null) {}

    async execute({
        invocation,
        action,
        result,
    }: ActionHandlerOptions<WaitUntilConditionAction>): Promise<ActionHandlerResult> {
        const hasEvents = (action.config.events?.length ?? 0) > 0
        const hasCondition = hasConfiguredCondition(action.config.condition?.filters)
        const isParked = invocation.state?.currentAction?.waitingForEvent === true

        if (hasEvents && !this.subscriptions) {
            logger.warn(
                'WaitUntilConditionHandler: events configured but subscriptions service not available, falling through',
                { actionId: action.id }
            )
            return { nextAction: findContinueAction(invocation) }
        }

        // 1. If this is a re-entry and we have event subscriptions, check for a matched event.
        if (isParked && hasEvents && this.subscriptions) {
            const remaining = await this.subscriptions.getForJob(invocation.id, 'wait_step')
            const matchedSub = remaining.find((s) => s.matchedEvent != null)

            if (matchedSub?.matchedEvent) {
                const eventName = matchedSub.matchedEvent.event
                result.logs.push({
                    level: 'info',
                    timestamp: DateTime.now(),
                    message: `Event '${eventName}' matched - taking the matched path`,
                })

                await this.subscriptions.deleteForJob(invocation.id, 'wait_step')
                this.clearWaitingFlag(invocation)

                return {
                    nextAction: findNextAction(invocation.hogFlow, action.id, 0),
                    result: matchedSub.matchedEvent,
                }
            }
        }

        // 2. Evaluate the person property condition (on every execution, first or re-entry).
        if (hasCondition) {
            const filterResults = await filterFunctionInstrumented({
                fn: invocation.hogFlow,
                filters: action.config.condition!.filters,
                filterGlobals: { ...invocation.filterGlobals, variables: invocation.state.variables },
            })

            if (filterResults.match) {
                result.logs.push({
                    level: 'info',
                    timestamp: DateTime.now(),
                    message: `Condition matched - taking the matched path`,
                })

                // Clean up any event subscriptions we created earlier.
                if (isParked && this.subscriptions) {
                    await this.subscriptions.deleteForJob(invocation.id, 'wait_step')
                }
                this.clearWaitingFlag(invocation)

                return { nextAction: findNextAction(invocation.hogFlow, action.id, 0) }
            }
        }

        // 3. No match - compute next schedule time (next poll or final timeout).
        const scheduledAt = calculatedScheduledAt(
            action.config.max_wait_duration,
            invocation.state?.currentAction?.startedAtTimestamp,
            DEFAULT_POLL_INTERVAL_SECONDS
        )

        if (!scheduledAt) {
            // Timeout reached - take the continue edge ("no match" path).
            const reasons: string[] = []
            if (hasEvents) {
                reasons.push('events')
            }
            if (hasCondition) {
                reasons.push('condition')
            }
            result.logs.push({
                level: 'info',
                timestamp: DateTime.now(),
                message: `Timed out waiting for ${reasons.join(' or ')} - taking the timeout path`,
            })

            if (isParked && this.subscriptions) {
                await this.subscriptions.deleteForJob(invocation.id, 'wait_step')
            }
            this.clearWaitingFlag(invocation)

            return { nextAction: findContinueAction(invocation) }
        }

        // 4. Still waiting - park the job. On first visit with events, create subscriptions.
        if (hasEvents && !isParked && this.subscriptions) {
            const personId = invocation.state?.personId ?? invocation.person?.id
            if (!personId) {
                logger.warn('WaitUntilConditionHandler: no personId, cannot create event subscriptions', {
                    actionId: action.id,
                    invocationId: invocation.id,
                })
                // Fall through without subscriptions - condition polling will still work.
            } else {
                await this.createSubscriptions(invocation, action, String(personId), scheduledAt)
                if (invocation.state?.currentAction) {
                    invocation.state.currentAction.waitingForEvent = true
                }

                const eventNames = action
                    .config!.events!.flatMap((e) => extractEventNames(e.filters))
                    .filter(Boolean)
                    .join(', ')
                result.logs.push({
                    level: 'info',
                    timestamp: DateTime.now(),
                    message: `Waiting for event${action.config.events!.length > 1 ? 's' : ''}: ${eventNames} (timeout: ${scheduledAt.toUTC().toISO()})`,
                })
            }
        } else if (!isParked && hasCondition) {
            result.logs.push({
                level: 'info',
                timestamp: DateTime.now(),
                message: `Waiting for condition to match (timeout: ${scheduledAt.toUTC().toISO()})`,
            })
        }

        return { scheduledAt }
    }

    private async createSubscriptions(
        invocation: ActionHandlerOptions<WaitUntilConditionAction>['invocation'],
        action: WaitUntilConditionAction,
        personId: string,
        expiresAt: DateTime
    ): Promise<void> {
        if (!this.subscriptions || !action.config.events?.length) {
            return
        }

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

        await this.subscriptions.createMany(subs)
    }

    private clearWaitingFlag(invocation: ActionHandlerOptions<WaitUntilConditionAction>['invocation']): void {
        if (invocation.state?.currentAction) {
            invocation.state.currentAction.waitingForEvent = false
        }
    }
}

/**
 * A condition is only considered configured if its filters contain actual
 * content: non-empty property filters, event filters, action filters, or
 * compiled bytecode. An empty `{}` or null should NOT be treated as a
 * configured condition, otherwise the empty-filter evaluation can match
 * anything and take the matched path on first visit.
 */
function hasConfiguredCondition(filters: any): boolean {
    if (!filters || typeof filters !== 'object') {
        return false
    }
    const hasProperties = Array.isArray(filters.properties) && filters.properties.length > 0
    const hasEvents = Array.isArray(filters.events) && filters.events.length > 0
    const hasActions = Array.isArray(filters.actions) && filters.actions.length > 0
    const hasBytecode = Array.isArray(filters.bytecode) && filters.bytecode.length > 0
    return hasProperties || hasEvents || hasActions || hasBytecode
}

/**
 * Extract ALL event names from the action filters config. The filters shape is
 * the standard PostHog filter envelope (`{ events: [{ id, name, type }, ...] }`).
 */
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
