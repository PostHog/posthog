import { DateTime } from 'luxon'

import { HogFlowAction } from '../../../../schema/hogflow'
import { CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '../../../types'
import { HogExecutorExecuteAsyncOptions } from '../../hog-executor.service'

export interface ActionHandlerResult {
    nextAction?: HogFlowAction
    scheduledAt?: DateTime
    finished?: boolean
    result?: unknown
    error?: any
}

export interface ActionHandlerOptions<T extends HogFlowAction> {
    invocation: CyclotronJobInvocationHogFlow
    action: T
    result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>
    hogExecutorOptions?: HogExecutorExecuteAsyncOptions
}

export interface ActionHandler {
    execute(options: ActionHandlerOptions<HogFlowAction>): ActionHandlerResult | Promise<ActionHandlerResult>
}
