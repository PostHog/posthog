import { CyclotronJobInvocationResult } from '~/src/cdp/types'
import { CyclotronJobInvocationHogFlow } from '~/src/cdp/types'
import { HogFlowAction } from '~/src/schema/hogflow'

export interface HogFlowActionRunner {
    run(
        invocation: CyclotronJobInvocationHogFlow,
        action: HogFlowAction
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>>
}
