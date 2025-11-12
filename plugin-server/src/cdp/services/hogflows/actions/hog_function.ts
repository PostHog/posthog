import { DateTime } from 'luxon'

import { HogFlowAction } from '../../../../schema/hogflow'
import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    MinimalLogEntry,
} from '../../../types'
import { HogExecutorExecuteAsyncOptions } from '../../hog-executor.service'
import { RecipientPreferencesService } from '../../messaging/recipient-preferences.service'
import { HogFlowFunctionsService } from '../hogflow-functions.service'
import { actionIdForLogging, findContinueAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'

type FunctionActionType = 'function' | 'function_email' | 'function_sms'

type Action = Extract<HogFlowAction, { type: FunctionActionType }>

export class HogFunctionHandler implements ActionHandler {
    constructor(
        private hogFlowFunctionsService: HogFlowFunctionsService,
        private recipientPreferencesService: RecipientPreferencesService
    ) {}

    async execute({
        invocation,
        action,
        result,
        hogExecutorOptions,
    }: ActionHandlerOptions<Action>): Promise<ActionHandlerResult> {
        const functionResult = await this.executeHogFunction(invocation, action, hogExecutorOptions)

        // Add all logs
        functionResult.logs.forEach((log: MinimalLogEntry) => {
            result.logs.push({
                level: log.level,
                timestamp: log.timestamp,
                message: `${actionIdForLogging(action)} ${log.message}`,
            })
        })

        // Collect captured PostHog events
        result.capturedPostHogEvents = [...result.capturedPostHogEvents, ...functionResult.capturedPostHogEvents]

        if (!functionResult.finished) {
            // Set the state of the function result on the substate of the flow for the next execution
            result.invocation.state.currentAction!.hogFunctionState = functionResult.invocation.state
            // Also the queueParameters are required
            result.invocation.queueParameters = functionResult.invocation.queueParameters
            return {
                scheduledAt: functionResult.invocation.queueScheduledAt ?? DateTime.now(),
            }
        }

        return {
            nextAction: findContinueAction(invocation),
            result: functionResult.execResult,
        }
    }

    private async executeHogFunction(
        invocation: CyclotronJobInvocationHogFlow,
        action: Action,
        hogExecutorOptions?: HogExecutorExecuteAsyncOptions
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        const hogFunction = await this.hogFlowFunctionsService.buildHogFunction(invocation.hogFlow, action.config)
        const hogFunctionInvocation = await this.hogFlowFunctionsService.buildHogFunctionInvocation(
            invocation,
            hogFunction,
            {
                event: invocation.state.event,
                person: invocation.person,
                variables: invocation.state.variables,
            }
        )

        if (await this.recipientPreferencesService.shouldSkipAction(hogFunctionInvocation, action)) {
            return {
                finished: true,
                invocation: hogFunctionInvocation,
                logs: [
                    {
                        level: 'info',
                        timestamp: DateTime.now(),
                        message: `Recipient opted out for action ${action.id}`,
                    },
                ],
                metrics: [],
                capturedPostHogEvents: [],
            }
        }

        return this.hogFlowFunctionsService.executeWithAsyncFunctions(hogFunctionInvocation, hogExecutorOptions)
    }
}
