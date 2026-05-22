import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInvocationGlobals,
    HogFunctionType,
} from '~/cdp/types'
import { HogFlow, HogFlowAction } from '~/schema/hogflow'

import { HogExecutorExecuteAsyncOptions, HogExecutorService } from '../hog-executor.service'
import { HogFunctionTemplateManagerService } from '../managers/hog-function-template-manager.service'

type FunctionActionType = 'function' | 'function_email' | 'function_sms'
type Action = Extract<HogFlowAction, { type: FunctionActionType }>

// Helper class that can turn a hog flow action into a hog function
export class HogFlowFunctionsService {
    constructor(
        private siteUrl: string,
        private hogFunctionTemplateManager: HogFunctionTemplateManagerService,
        private hogFunctionExecutor: HogExecutorService
    ) {}

    async buildHogFunction(hogFlow: HogFlow, configuration: Action['config']): Promise<HogFunctionType> {
        const template = await this.hogFunctionTemplateManager.getHogFunctionTemplate(configuration.template_id)

        if (!template) {
            throw new Error(`Template '${configuration.template_id}' not found`)
        }

        const { inputs, mappings, ...config } = configuration

        const hogFunction: HogFunctionType = {
            id: hogFlow.id,
            team_id: hogFlow.team_id,
            name: `${hogFlow.name} - ${template.name}`,
            enabled: true,
            type: template.type,
            deleted: false,
            hog: '<<TEMPLATE>>',
            bytecode: template.bytecode,
            inputs,
            inputs_schema: template.inputs_schema,
            template_id: template.template_id,
            mappings,
            created_at: '',
            updated_at: '',
            metadata: config,
        }

        return hogFunction
    }

    async buildHogFunctionInvocation(
        invocation: CyclotronJobInvocationHogFlow,
        hogFunction: HogFunctionType,
        globals: Omit<HogFunctionInvocationGlobals, 'source' | 'project'>
    ): Promise<CyclotronJobInvocationHogFunction> {
        const teamId = invocation.hogFlow.team_id
        const projectUrl = `${this.siteUrl}/project/${teamId}`

        const globalsWithSource: HogFunctionInvocationGlobals = {
            ...globals,
            // Include workflow-level variables
            variables: invocation.state.variables,
            source: {
                name: hogFunction.name ?? `Hog flow: ${invocation.hogFlow.id}`,
                url: `${projectUrl}/workflows/${invocation.hogFlow.id}/workflow?node=${hogFunction.id}`,
            },
            project: {
                id: hogFunction.team_id,
                name: '',
                url: '',
            },
        }

        // Globals (event, person, inputs) are always derived here — the queue
        // only persists the raw event. On resume we keep the persisted
        // vmState/timings/attempts but re-derive globals, so a mid-async
        // function still sees current person/inputs.
        const globalsWithInputs = await this.hogFunctionExecutor.buildInputsWithGlobals(hogFunction, globalsWithSource)
        const persistedState = invocation.state.currentAction?.hogFunctionState

        const hogFunctionInvocation: CyclotronJobInvocationHogFunction = {
            ...invocation,
            hogFunction,
            state: persistedState
                ? { ...persistedState, globals: globalsWithInputs }
                : {
                      globals: globalsWithInputs,
                      timings: [],
                      attempts: 0,
                      actionId: invocation.state.currentAction?.id,
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
