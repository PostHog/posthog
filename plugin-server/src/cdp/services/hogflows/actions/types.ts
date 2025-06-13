import { DateTime } from 'luxon'

import { CyclotronJobInvocationHogFlow } from '~/src/cdp/types'
import { HogFlowAction } from '~/src/schema/hogflow'

// Opinionated version of the CyclotronJobInvocationResult limiting what an action can do
export type HogFlowActionRunnerResult = {
    finished: boolean
    scheduledAt?: DateTime
    goToActionId?: string
}
export interface HogFlowActionRunnerType<T extends HogFlowAction> {
    run(invocation: CyclotronJobInvocationHogFlow, action: T): Promise<HogFlowActionRunnerResult>
}
