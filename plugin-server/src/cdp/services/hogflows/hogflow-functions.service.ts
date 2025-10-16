import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInvocationGlobals,
    HogFunctionType,
} from '~/cdp/types'
import { HogFlow, HogFlowAction } from '~/schema/hogflow'
import { Hub } from '~/types'

import { HogExecutorExecuteAsyncOptions, HogExecutorService } from '../hog-executor.service'
import { HogFunctionTemplateManagerService } from '../managers/hog-function-template-manager.service'

type FunctionActionType = 'function' | 'function_email' | 'function_sms'
type Action = Extract<HogFlowAction, { type: FunctionActionType }>

// Helper class that can turn a hog flow action into a hog function
export class HogFlowFunctionsService {
    constructor(
        private hub: Hub,
        private hogFunctionTemplateManager: HogFunctionTemplateManagerService,
        private hogFunctionExecutor: HogExecutorService
    ) {}

    async buildHogFunction(hogFlow: HogFlow, configuration: Action['config']): Promise<HogFunctionType> {
        const template = await this.hogFunctionTemplateManager.getHogFunctionTemplate(configuration.template_id)

        if (!template) {
            throw new Error(`Template '${configuration.template_id}' not found`)
        }

        const hogFunction: HogFunctionType = {
            id: hogFlow.id,
            team_id: hogFlow.team_id,
            name: `${hogFlow.name} - ${template.name}`,
            enabled: true,
            type: template.type,
            deleted: false,
            hog: '<<TEMPLATE>>',
            bytecode: template.bytecode,
            inputs: configuration.inputs,
            inputs_schema: template.inputs_schema,
            created_at: '',
            updated_at: '',
        }

        return hogFunction
    }

    async buildHogFunctionInvocation(
        invocation: CyclotronJobInvocationHogFlow,
        hogFunction: HogFunctionType,
        globals: Omit<HogFunctionInvocationGlobals, 'source' | 'project'>
    ): Promise<CyclotronJobInvocationHogFunction> {
        const teamId = invocation.hogFlow.team_id
        const projectUrl = `${this.hub.SITE_URL}/project/${teamId}`

        const globalsWithSource: HogFunctionInvocationGlobals = {
            ...globals,
            source: {
                name: hogFunction.name ?? `Hog flow: ${invocation.hogFlow.id}`,
                url: `${projectUrl}/messaging/campaigns/${invocation.hogFlow.id}/workflow?node=${hogFunction.id}`,
            },
            project: {
                id: hogFunction.team_id,
                name: '',
                url: '',
            },
        }

        const hogFunctionInvocation: CyclotronJobInvocationHogFunction = {
            ...invocation,
            hogFunction,
            state: invocation.state.currentAction?.hogFunctionState ?? {
                globals: await this.hogFunctionExecutor.buildInputsWithGlobals(hogFunction, globalsWithSource),
                timings: [],
                attempts: 0,
            },
        }

        return hogFunctionInvocation
    }

    async execute(
        invocation: CyclotronJobInvocationHogFunction
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        return this.hogFunctionExecutor.execute(invocation)
    }

    async executeWithAsyncFunctions(
        invocation: CyclotronJobInvocationHogFunction,
        hogExecutorOptions?: HogExecutorExecuteAsyncOptions
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        return this.hogFunctionExecutor.executeWithAsyncFunctions(invocation, hogExecutorOptions)
    }
}
