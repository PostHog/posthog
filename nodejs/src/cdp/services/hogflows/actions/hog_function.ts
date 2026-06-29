import { DateTime } from 'luxon'

import { HogFlowAction } from '~/cdp/schema/hogflow'

import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    MinimalLogEntry,
} from '../../../types'
import { HogExecutorExecuteAsyncOptions } from '../../hog-executor.service'
import { RecipientPreferencesService } from '../../messaging/recipient-preferences.service'
import { trackHogFlowBillableInvocation } from '../billing-utils'
import { HogFlowFunctionsService } from '../hogflow-functions.service'
import { actionIdForLogging, findContinueAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'

type FunctionActionType = 'function' | 'function_email' | 'function_sms'

type Action = Extract<HogFlowAction, { type: FunctionActionType }>

export class HogFunctionHandler implements ActionHandler {
    constructor(
        private hogFlowFunctionsService: HogFlowFunctionsService,
        private recipientPreferencesService: RecipientPreferencesService,
        private hogFlowActionBillingType: 'fetch' | 'email'
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

        // Collect captured PostHog events and metrics from the function execution
        result.capturedPostHogEvents = [...result.capturedPostHogEvents, ...functionResult.capturedPostHogEvents]
        // Collect warehouse webhook payloads
        result.warehouseWebhookPayloads = [
            ...result.warehouseWebhookPayloads,
            ...functionResult.warehouseWebhookPayloads,
        ]
        result.metrics = [...result.metrics, ...functionResult.metrics]

        if (!functionResult.finished) {
            // Set the state of the function result on the substate of the flow for the next execution
            result.invocation.state.currentAction!.hogFunctionState = functionResult.invocation.state
            // Preserve queue routing and parameters from the function result
            result.invocation.queue = functionResult.invocation.queue
            result.invocation.queueParameters = functionResult.invocation.queueParameters
            result.invocation.queueMetadata = functionResult.invocation.queueMetadata
            // Routing-only reschedule signature: the queue changed AND no explicit
            // `queueScheduledAt` was set. That's the shape produced by `routeEmailToQueue`
            // and `routeToQueue` in hog-executor.service.ts when moving a job between the
            // hogflow and email queues — the next dequeue continues the same action on the
            // new queue. Tag the action state so the executor can suppress the redundant
            // "Resuming..." / "Workflow will pause until..." pair on the next dequeue.
            //
            // The queue-changed check is what keeps async pauses (fetches, SES throttle
            // retries) out of this branch: both keep `queueScheduledAt` set OR leave the
            // queue unchanged, so they don't satisfy both halves of the condition.
            const queueChanged = functionResult.invocation.queue !== invocation.queue
            if (queueChanged && !functionResult.invocation.queueScheduledAt) {
                result.invocation.state.currentAction!.routingOnlyReschedule = true
            }
            return {
                scheduledAt: functionResult.invocation.queueScheduledAt ?? DateTime.now(),
            }
        }

        // Add billable_invocation metric only if the function actually executed (not skipped)
        if (!functionResult.skipped) {
            trackHogFlowBillableInvocation(result, {
                invocation: functionResult.invocation,
                billingMetricType: this.hogFlowActionBillingType,
            })
        }

        return {
            nextAction: findContinueAction(invocation),
            result: functionResult.execResult,
            error: functionResult.error,
        }
    }

    private async executeHogFunction(
        invocation: CyclotronJobInvocationHogFlow,
        action: Action,
        hogExecutorOptions?: HogExecutorExecuteAsyncOptions
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> & { skipped?: boolean }> {
        const hogFunction = await this.hogFlowFunctionsService.buildHogFunction(invocation.hogFlow, action.config)
        const hogFunctionInvocation = await this.hogFlowFunctionsService.buildHogFunctionInvocation(
            invocation,
            hogFunction,
            {
                event: invocation.state.event,
                person: invocation.person,
                groups: invocation.groups,
                variables: invocation.state.variables,
            }
        )

        if (await this.recipientPreferencesService.shouldSkipAction(hogFunctionInvocation, action)) {
            return {
                finished: true,
                skipped: true,
                invocation: hogFunctionInvocation,
                logs: [
                    {
                        level: 'info',
                        timestamp: DateTime.now(),
                        message: `Recipient has opted out, skipping message delivery.`,
                    },
                ],
                metrics: [],
                capturedPostHogEvents: [],
                warehouseWebhookPayloads: [],
            }
        }

        return this.hogFlowFunctionsService.executeWithAsyncFunctions(hogFunctionInvocation, hogExecutorOptions)
    }
}
