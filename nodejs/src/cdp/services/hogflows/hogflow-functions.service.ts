import { HogFlow, HogFlowAction } from '~/cdp/schema/hogflow'
import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInvocationGlobals,
    HogFunctionType,
} from '~/cdp/types'

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

    // Collect the decrypted secret input values across a flow's function actions, so a test
    // invocation with mocked async functions can redact them from the fetch args it echoes into logs
    // (otherwise a workflow editor could read a stored credential they were never shown).
    async getSensitiveValues(hogFlow: HogFlow): Promise<string[]> {
        const functionActionTypes: FunctionActionType[] = ['function', 'function_email', 'function_sms']
        const values: string[] = []
        for (const action of hogFlow.actions ?? []) {
            if (!functionActionTypes.includes(action.type as FunctionActionType)) {
                continue
            }
            const config = (action as Action).config
            const template = await this.hogFunctionTemplateManager.getHogFunctionTemplate(config.template_id)
            for (const schema of template?.inputs_schema ?? []) {
                if (!schema.secret) {
                    continue
                }
                const value = config.inputs?.[schema.key]?.value
                if (typeof value === 'string') {
                    values.push(value)
                } else if (value && typeof value === 'object') {
                    // e.g. a headers dict {Authorization: "Bearer <key>"} - mask each string leaf
                    Object.values(value).forEach((leaf) => {
                        if (typeof leaf === 'string') {
                            values.push(leaf)
                        }
                    })
                }
            }
        }
        return values
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

        const hogFunctionInvocation: CyclotronJobInvocationHogFunction = {
            ...invocation,
            hogFunction,
            state: invocation.state.currentAction?.hogFunctionState ?? {
                globals: await this.hogFunctionExecutor.buildInputsWithGlobals(hogFunction, globalsWithSource),
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
