import { DateTime } from 'luxon'

import { HogFlowAction } from '../../../../schema/hogflow'
import { Hub } from '../../../../types'
import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInvocationGlobals,
    HogFunctionType,
    MinimalLogEntry,
} from '../../../types'
import { HogExecutorService } from '../../hog-executor.service'
import { HogFunctionTemplateManagerService } from '../../managers/hog-function-template-manager.service'
import { RecipientsManagerService } from '../../managers/recipients-manager.service'
import { findContinueAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerResult } from './action.interface'

export class HogFunctionHandler implements ActionHandler {
    constructor(
        private hub: Hub,
        private hogFunctionExecutor: HogExecutorService,
        private hogFunctionTemplateManager: HogFunctionTemplateManagerService,
        private recipientsManager: RecipientsManagerService
    ) {}

    async execute(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<
            HogFlowAction,
            { type: 'function' | 'function_email' | 'function_sms' | 'function_slack' | 'function_webhook' }
        >,
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFlow>
    ): Promise<ActionHandlerResult> {
        const functionResult = await this.executeHogFunction(invocation, action)

        // Add all logs
        functionResult.logs.forEach((log: MinimalLogEntry) => {
            result.logs.push({
                level: log.level,
                timestamp: log.timestamp,
                message: `[Action:${action.id}] ${log.message}`,
            })
        })

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
        }
    }

    private async executeHogFunction(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<
            HogFlowAction,
            { type: 'function' | 'function_email' | 'function_sms' | 'function_slack' | 'function_webhook' }
        >
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        const template = await this.hogFunctionTemplateManager.getHogFunctionTemplate(action.config.template_id)

        if (!template) {
            throw new Error(`Template '${action.config.template_id}' not found`)
        }

        const hogFunction: HogFunctionType = {
            id: invocation.hogFlow.id,
            team_id: invocation.teamId,
            name: `${invocation.hogFlow.name} - ${template.name}`,
            enabled: true,
            type: 'destination',
            deleted: false,
            hog: '<<TEMPLATE>>',
            bytecode: template.bytecode,
            inputs: action.config.inputs,
            inputs_schema: template.inputs_schema,
            is_addon_required: false,
            created_at: '',
            updated_at: '',
        }

        const teamId = invocation.hogFlow.team_id
        const projectUrl = `${this.hub.SITE_URL}/project/${teamId}`

        const globals: HogFunctionInvocationGlobals = {
            source: {
                name: hogFunction.name ?? `Hog function: ${hogFunction.id}`,
                url: `${projectUrl}/functions/${hogFunction.id}`,
            },
            project: {
                id: hogFunction.team_id,
                name: '',
                url: '',
            },
            event: invocation.state.event,
            person: invocation.person,
        }

        const hogFunctionInvocation: CyclotronJobInvocationHogFunction = {
            ...invocation,
            hogFunction,
            state: invocation.state.currentAction?.hogFunctionState ?? {
                globals: await this.hogFunctionExecutor.buildInputsWithGlobals(hogFunction, globals),
                timings: [],
                attempts: 0,
            },
        }

        // Check recipient preferences for email and SMS actions
        if (this.isSubjectToRecipientPreferences(action)) {
            const { isOptedOut } = await this.checkRecipientPreferences(invocation, action)
            if (isOptedOut) {
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
        }

        return this.hogFunctionExecutor.executeWithAsyncFunctions(hogFunctionInvocation)
    }

    private isSubjectToRecipientPreferences(
        action: HogFlowAction
    ): action is Extract<HogFlowAction, { type: 'function_email' | 'function_sms' }> {
        return ['function_email', 'function_sms'].includes(action.type)
    }

    private async checkRecipientPreferences(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<HogFlowAction, { type: 'function_email' | 'function_sms' }>
    ): Promise<{ isOptedOut: boolean }> {
        // Get the identifier to be used from the action config for sms, this is an input called to_number,
        // for email it is inside an input called email, specifically email.to.
        let identifier

        if (action.type === 'function_sms') {
            identifier = action.config.inputs?.to_number
        } else if (action.type === 'function_email') {
            identifier = action.config.inputs?.email?.value?.to
        }

        if (!identifier) {
            throw new Error(`No identifier found for message action ${action.id}`)
        }

        try {
            const recipient = await this.recipientsManager.get({
                teamId: invocation.teamId,
                identifier: identifier,
            })

            if (recipient) {
                // Grab the recipient preferences for the action category
                const categoryId = action.config.message_category_id || '$all'

                const preference = this.recipientsManager.getPreference(recipient, categoryId)
                if (preference === 'OPTED_OUT') {
                    return {
                        isOptedOut: true,
                    }
                }
            }

            return {
                isOptedOut: false,
            }
        } catch (error) {
            // Log error but don't fail the execution
            console.error(`Failed to fetch recipient preferences for ${identifier}:`, error)
            return {
                isOptedOut: false,
            }
        }
    }
}
