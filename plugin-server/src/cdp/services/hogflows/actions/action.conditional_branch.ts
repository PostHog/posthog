import { CyclotronJobInvocationHogFlow, HogFunctionFilterGlobals } from '~/cdp/types'
import { convertToHogFunctionFilterGlobal } from '~/cdp/utils'
import { filterFunctionInstrumented } from '~/cdp/utils/hog-function-filtering'
import { HogFlowAction } from '~/schema/hogflow'

import { calculatedScheduledAt } from './common/delay'
import { HogFlowActionResult } from './types'
import { findNextAction } from './utils'

const DEFAULT_WAIT_DURATION_SECONDS = 10 * 60

export class HogFlowActionRunnerConditionalBranch {
    run(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<HogFlowAction, { type: 'conditional_branch' }>
    ): HogFlowActionResult {
        const filterGlobals: HogFunctionFilterGlobals = convertToHogFunctionFilterGlobal({
            event: invocation.state.event, // TODO: Fix typing
            groups: {},
        })

        // the index is used to find the right edge
        for (const [index, condition] of action.config.conditions.entries()) {
            // TODO(messaging): Figure out error handling here - do we throw or just move on to other conditions?
            const filterResults = filterFunctionInstrumented({
                fn: invocation.hogFlow,
                filters: condition.filter,
                filterGlobals,
                eventUuid: invocation.state.event.uuid,
            })

            if (filterResults.match) {
                return {
                    done: true,
                    // TODO: Should we throw if not found - or at least log something?
                    goToAction: findNextAction(invocation.hogFlow, action.id, index),
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
                    done: false,
                    scheduledAt,
                }
            }
        }

        return {
            done: true,
        }
    }

    // NOTE: Wait until condition is a special case of conditional branch, so we reuse the same logic
    runWaitUntilCondition(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<HogFlowAction, { type: 'wait_until_condition' }>
    ): HogFlowActionResult {
        return this.run(invocation, {
            ...action,
            type: 'conditional_branch',
            config: {
                conditions: [action.config.condition],
                delay_duration: action.config.max_wait_duration,
            },
        })
    }
}
