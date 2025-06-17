import { CyclotronJobInvocationHogFlow, HogFunctionFilterGlobals } from '~/cdp/types'
import { convertToHogFunctionFilterGlobal } from '~/cdp/utils'
import { filterFunctionInstrumented } from '~/cdp/utils/hog-function-filtering'
import { HogFlowAction } from '~/schema/hogflow'

import { calculatedScheduledAt } from './common/delay'
import { HogFlowActionRunnerResult } from './types'

const DEFAULT_WAIT_DURATION_SECONDS = 10 * 60

// NOTE: This is almost identical to the conditional branch action, but we don't need to check for multiple conditions - we could consolidate
export class HogFlowActionRunnerWaitForCondition {
    run(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<HogFlowAction, { type: 'wait_until_condition' }>
    ): Promise<HogFlowActionRunnerResult> {
        const filterGlobals: HogFunctionFilterGlobals = convertToHogFunctionFilterGlobal({
            event: invocation.state.event, // TODO: Fix typing
            groups: {},
        })

        const filterResults = filterFunctionInstrumented({
            fn: invocation.hogFlow,
            filters: action.config.condition.filter,
            filterGlobals,
            eventUuid: invocation.state.event.uuid,
        })

        if (filterResults.match) {
            return Promise.resolve({
                finished: true,
                goToActionId: action.config.condition.on_match,
            })
        }

        if (action.config.max_wait_duration) {
            // Calculate the scheduledAt based on the delay duration - max we will wait for is 10 minutes which means we check every 10 minutes until the condition is met
            const scheduledAt = calculatedScheduledAt(
                action.config.max_wait_duration,
                invocation.state.currentAction?.startedAtTimestamp,
                DEFAULT_WAIT_DURATION_SECONDS
            )

            return Promise.resolve({
                finished: !scheduledAt,
                scheduledAt: scheduledAt ?? undefined,
            })
        }

        return Promise.resolve({
            finished: true,
        })
    }
}
