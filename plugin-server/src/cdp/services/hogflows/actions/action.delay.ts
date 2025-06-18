import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { HogFlowAction } from '~/schema/hogflow'

import { calculatedScheduledAt } from './common/delay'
import { HogFlowActionResult } from './types'

export class HogFlowActionRunnerDelay {
    run(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<HogFlowAction, { type: 'delay' }>
    ): HogFlowActionResult {
        const scheduledAt = calculatedScheduledAt(
            action.config.delay_duration,
            invocation.state.currentAction?.startedAtTimestamp
        )

        if (scheduledAt) {
            return {
                done: false,
                scheduledAt,
            }
        }

        return {
            done: true,
        }
    }
}
