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
                  }
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
    action: Extract<HogFlowAction, { type: 'conditional_branch' }>
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
        // Calculate the scheduledAt based on the delay duration - max we will wait for is 10 minutes which means we check every 10 minutes until the condition is met
        const scheduledAt = calculatedScheduledAt(
            action.config.delay_duration,
            invocation.state.currentAction?.startedAtTimestamp,
            DEFAULT_WAIT_DURATION_SECONDS
        )

        if (scheduledAt) {
            return {
                scheduledAt,
            }
        }
    }
    return {}
}
