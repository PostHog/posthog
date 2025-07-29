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
import { findContinueAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerResult } from './action.interface'

export class HogFunctionHandler implements ActionHandler {
    constructor(
        private hub: Hub,
        private hogFunctionExecutor: HogExecutorService,
        private hogFunctionTemplateManager: HogFunctionTemplateManagerService
    ) {}

    async execute(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<HogFlowAction, { type: 'function' }>,
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
        action: Extract<HogFlowAction, { type: 'function' }>
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

        return this.hogFunctionExecutor.executeWithAsyncFunctions(hogFunctionInvocation)
    }
}
