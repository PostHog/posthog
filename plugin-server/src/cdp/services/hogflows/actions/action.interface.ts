import { DateTime } from 'luxon'

import { HogFlowAction } from '../../../../schema/hogflow'
import { CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '../../../types'

export interface ActionHandlerResult {
    nextAction?: HogFlowAction
    scheduledAt?: DateTime
    finished?: boolean
}

export interface ActionHandler {
    execute(
        invocation: CyclotronJobInvocationHogFlow,
        action: HogFlowAction,
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>
    ): ActionHandlerResult | Promise<ActionHandlerResult>
}
