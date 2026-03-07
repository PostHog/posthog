import { DateTime } from 'luxon'

import { CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '~/cdp/types'
import { filterFunctionInstrumented } from '~/cdp/utils/hog-function-filtering'
import { HogFlowAction } from '~/schema/hogflow'

import { actionIdForLogging, findContinueAction, findNextAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'
import { calculatedScheduledAt } from './delay'

const DEFAULT_WAIT_DURATION_SECONDS = 10 * 60

export class ConditionalBranchHandler implements ActionHandler {
    async execute({
        invocation,
        action,
        result,
    }: ActionHandlerOptions<
        Extract<HogFlowAction, { type: 'conditional_branch' | 'wait_until_condition' }>
    >): Promise<ActionHandlerResult> {
        const conditionResult = await checkConditions(
            invocation,
            action.type === 'conditional_branch'
                ? action
                : {
                      ...action,
                      type: 'conditional_branch',
                      config: {
                          conditions: [action.config.condition],
                          delay_duration: action.config.max_wait_duration,
                      },
                  }
        )

        if (conditionResult.scheduledAt) {
            logDebug(
                result,
                `${actionIdForLogging(action)} matched no condition and was scheduled for re-evaluation at ${conditionResult.scheduledAt.toUTC().toISO()}`
            )
            return { scheduledAt: conditionResult.scheduledAt, result: { conditionResult } }
        } else if (conditionResult.nextAction) {
            logDebug(
                result,
                `${actionIdForLogging(action)} matched ${formatConditionName(conditionResult.matchedConditionIndex, conditionResult.matchedConditionName)}`
            )
            return { nextAction: conditionResult.nextAction, result: { conditionResult } }
        }

        logDebug(result, `${actionIdForLogging(action)} matched no condition`)
        return { nextAction: findContinueAction(invocation), result: { conditionResult } }
    }
}

export async function checkConditions(
    invocation: CyclotronJobInvocationHogFlow,
    action: Extract<HogFlowAction, { type: 'conditional_branch' }>
): Promise<{
    scheduledAt?: DateTime
    nextAction?: HogFlowAction
    matchedConditionIndex?: number
    matchedConditionName?: string
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
                matchedConditionIndex: index,
                matchedConditionName: condition.name,
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

function formatConditionName(matchedConditionIndex?: number, matchedConditionName?: string): string {
    if (matchedConditionIndex === undefined) {
        return 'a condition'
    }
    if (!matchedConditionName) {
        return `condition ${matchedConditionIndex + 1}`
    }
    return `condition ${matchedConditionIndex + 1} (${matchedConditionName})`
}

function logDebug(result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>, message: string): void {
    result.logs.push({ level: 'debug', timestamp: DateTime.now(), message })
}
