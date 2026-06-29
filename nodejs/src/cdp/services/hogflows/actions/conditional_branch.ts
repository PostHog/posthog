import { DateTime } from 'luxon'

import { HogFlowAction } from '~/cdp/schema/hogflow'
import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { filterFunctionInstrumented } from '~/cdp/utils/hog-function-filtering'

import { findContinueAction, findNextAction, isEvaluableCondition } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'
import { calculatedScheduledAt } from './delay'

const DEFAULT_WAIT_DURATION_SECONDS = 10 * 60

export class ConditionalBranchHandler implements ActionHandler {
    async execute({
        invocation,
        action,
    }: ActionHandlerOptions<
        Extract<HogFlowAction, { type: 'conditional_branch' | 'wait_until_condition' }>
    >): Promise<ActionHandlerResult> {
        // The subscription matcher sets eventMatched when an incoming event matched this
        // step's wait condition. Honor it as a forced match and advance immediately,
        // rather than re-evaluating the stored condition against the original event.
        if (action.type === 'wait_until_condition' && invocation.state?.currentAction?.eventMatched === true) {
            invocation.state.currentAction.eventMatched = false
            invocation.state.currentAction.eventMatchedEvent = undefined
            invocation.state.currentAction.eventMatchedEventUuid = undefined
            return {
                nextAction: findNextAction(invocation.hogFlow, action.id, 0),
                result: { eventMatched: true },
            }
        }

        const conditionResult = await checkConditions(
            invocation,
            action.type === 'conditional_branch'
                ? action
                : {
                      ...action,
                      type: 'conditional_branch',
                      config: {
                          // An empty condition compiles to always-true bytecode, which would match on
                          // entry and fire the wait immediately. Only honor a condition with a real
                          // compiled filter; otherwise the wait relies on its events / the timeout.
                          conditions: isEvaluableCondition(action.config.condition) ? [action.config.condition] : [],
                          delay_duration: action.config.max_wait_duration,
                      },
                  },
            // A wait_until_condition is woken event-driven by the subscription matcher, so it parks
            // once to its full max_wait deadline (the timeout) instead of re-parking every 10 minutes.
            // The 10-minute cap is kept for a plain conditional_branch, which has no matcher backstop.
            { singleDeepPark: action.type === 'wait_until_condition' }
        )

        if (conditionResult.scheduledAt) {
            return { scheduledAt: conditionResult.scheduledAt, result: { conditionResult } }
        } else if (conditionResult.nextAction) {
            return { nextAction: conditionResult.nextAction, result: { conditionResult } }
        }

        return { nextAction: findContinueAction(invocation), result: { conditionResult } }
    }
}

export async function checkConditions(
    invocation: CyclotronJobInvocationHogFlow,
    action: Extract<HogFlowAction, { type: 'conditional_branch' }>,
    options?: { singleDeepPark?: boolean }
): Promise<{
    scheduledAt?: DateTime
    nextAction?: HogFlowAction
}> {
    // the index is used to find the right edge
    for (const [index, condition] of action.config.conditions.entries()) {
        // TODO(team-workflows): Figure out error handling here - do we throw or just move on to other conditions?
        const filterResults = await filterFunctionInstrumented({
            fn: invocation.hogFlow,
            filters: condition.filters,
            filterGlobals: { ...invocation.filterGlobals, variables: invocation.state.variables },
        })

        if (filterResults.match) {
            return {
                nextAction: findNextAction(invocation.hogFlow, action.id, index),
            }
        }
    }

    if (action.config.delay_duration) {
        // Single deep park (wait_until_condition): park once to the full delay_duration deadline and
        // let the subscription matcher wake the job early on any matching signal. Otherwise (plain
        // conditional_branch) keep the 10-minute cap so it re-checks the condition by polling.
        const scheduledAt = calculatedScheduledAt(
            action.config.delay_duration,
            invocation.state.currentAction?.startedAtTimestamp,
            options?.singleDeepPark ? undefined : DEFAULT_WAIT_DURATION_SECONDS
        )

        if (scheduledAt) {
            return {
                scheduledAt,
            }
        }
    }
    return {}
}
