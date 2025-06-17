import { CyclotronJobInvocationHogFlow, HogFunctionFilterGlobals } from '~/cdp/types'
import { convertToHogFunctionFilterGlobal } from '~/cdp/utils'
import { filterFunctionInstrumented } from '~/cdp/utils/hog-function-filtering'
import { HogFlowAction } from '~/schema/hogflow'

import { calculatedScheduledAt } from './common/delay'
import { HogFlowActionRunnerResult } from './types'

const DEFAULT_WAIT_DURATION_SECONDS = 10 * 60

export class HogFlowActionRunnerConditionalBranch {
    run(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<HogFlowAction, { type: 'conditional_branch' }>
    ): Promise<HogFlowActionRunnerResult> {
        const filterGlobals: HogFunctionFilterGlobals = convertToHogFunctionFilterGlobal({
            event: invocation.state.event, // TODO: Fix typing
            groups: {},
        })

        for (const condition of action.config.conditions) {
            const filterResults = filterFunctionInstrumented({
                fn: invocation.hogFlow,
                filters: condition.filter,
                filterGlobals,
                eventUuid: invocation.state.event.uuid,
            })

            if (filterResults.match) {
                return Promise.resolve({
                    finished: true,
                    goToActionId: condition.on_match,
                })
            }
        }

        // TODO: Add support for some sort of wait condition? Like if we are waiting for a period of time then we can go async

        if (action.config.delay_duration) {
            // Calculate the scheduledAt based on the delay duration - max we will wait for is 10 minutes which means we check every 10 minutes until the condition is met
            const scheduledAt = calculatedScheduledAt(
                action.config.delay_duration,
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
