import { CyclotronJobInvocationResult } from '~/src/cdp/types'
import { CyclotronJobInvocationHogFlow } from '~/src/cdp/types'
import { HogFlowAction } from '~/src/schema/hogflow'

export interface HogFlowActionRunnerType<T extends HogFlowAction> {
    run(
        invocation: CyclotronJobInvocationHogFlow,
        action: T
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>>
}
