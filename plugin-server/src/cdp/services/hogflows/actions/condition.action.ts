import { CyclotronJobInvocationHogFlow } from '~/src/cdp/types'
import { CyclotronJobInvocationResult } from '~/src/cdp/types'
import { createInvocationResult } from '~/src/cdp/utils/invocation-utils'
import { HogFlowAction } from '~/src/schema/hogflow'
import { logger } from '~/src/utils/logger'

import { HogFlowActionRunnerType } from './types'

// Can I somehow get the concrete type for this action from HogFlowAction?

type ConditionalBranchAction = Extract<HogFlowAction, { type: 'conditional_branch' }>

export class HogFlowActionRunnerCondition implements HogFlowActionRunnerType<ConditionalBranchAction> {
    async run(
        invocation: CyclotronJobInvocationHogFlow,
        action: ConditionalBranchAction
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>> {
        logger.info('🦔', `[HogFlowActionRunnerCondition] Running condition action`, {
            action,
            invocation,
        })

        await Promise.resolve()

        return createInvocationResult(
            invocation,
            {
                queue: 'hogflow',
            },
            {
                finished: true,
                capturedPostHogEvents: [],
                logs: [],
                metrics: [],
            }
        )
    }
}
