import { DateTime } from 'luxon'

import { HogFlowAction } from '~/cdp/schema/hogflow'

import { CyclotronJobInvocationHogFlow, CyclotronJobInvocationResult } from '../../../types'
import { HogExecutorExecuteAsyncOptions } from '../../hog-executor-async.service'

export interface ActionHandlerResult {
    nextAction?: HogFlowAction
    scheduledAt?: DateTime
    finished?: boolean
    /** The action deliberately ended the invocation because its input did not match. */
    skipped?: boolean
    result?: unknown
    testOutput?: unknown
    error?: any
}

/** Set only by the editor's test run. A native step that calls out reads it to mock its call. */
export type TestRunOptions = { mockAsyncFunctions: boolean; mockAnswer?: string }

export interface ActionHandlerOptions<T extends HogFlowAction> {
    invocation: CyclotronJobInvocationHogFlow
    action: T
    result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>
    hogExecutorOptions?: HogExecutorExecuteAsyncOptions
    testRun?: TestRunOptions
}

export interface ActionHandler {
    execute(options: ActionHandlerOptions<HogFlowAction>): ActionHandlerResult | Promise<ActionHandlerResult>
}
