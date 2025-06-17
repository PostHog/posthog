import { CyclotronJobInvocationHogFlow } from '~/cdp/types'
import { HogFlowAction } from '~/schema/hogflow'

import { calculatedScheduledAt } from './common/delay'
import { HogFlowActionRunnerResult } from './types'

export class HogFlowActionRunnerDelay {
    run(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<HogFlowAction, { type: 'delay' }>
    ): Promise<HogFlowActionRunnerResult> {
        const scheduledAt = calculatedScheduledAt(
            action.config.delay_duration,
            invocation.state.currentAction?.startedAtTimestamp
        )

        return Promise.resolve({
            finished: !scheduledAt,
            scheduledAt: scheduledAt ?? undefined,
        })
    }
}
