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
import { HogFlowActionTemplateManagerService } from './hogflow-action-template-manager.service'

type FunctionActionType = 'function' | 'function_email' | 'function_sms'
type Action = Extract<HogFlowAction, { type: FunctionActionType }>

// Helper class that can turn a hog flow action into a hog function
export class HogFlowFunctionsService {
    constructor(
        private siteUrl: string,
        private hogFunctionTemplateManager: HogFunctionTemplateManagerService,
        private hogFunctionExecutor: HogExecutorService,
        private hogFlowActionTemplateManager: HogFlowActionTemplateManagerService
    ) {}

    async buildHogFunction(hogFlow: HogFlow, configuration: Action['config']): Promise<HogFunctionType> {
        const { inputs: configInputs, mappings: configMappings, ...config } = configuration
        let inputs = configInputs
        let mappings = configMappings
        let catalogTemplateId: string = config.template_id

        // A linked step stores only a reference to a saved action template; the row is the single
        // source of truth for inputs/mappings so template edits propagate without re-saving flows.
        const actionTemplateId = 'action_template_id' in config ? config.action_template_id : undefined
        if (actionTemplateId) {
            const actionTemplate = await this.hogFlowActionTemplateManager.getHogFlowActionTemplate(actionTemplateId)
            // The cache is keyed by id across teams, so the team check must happen post-load.
            // A dangling or cross-team reference fails closed via the action's on_error handling.
            if (!actionTemplate || actionTemplate.team_id !== hogFlow.team_id) {
                throw new Error(`Action template '${actionTemplateId}' not found`)
            }
            catalogTemplateId = actionTemplate.template_id
            const encryptedInputs =
                actionTemplate.encrypted_inputs && typeof actionTemplate.encrypted_inputs === 'object'
                    ? actionTemplate.encrypted_inputs
                    : {}
            inputs = { ...(actionTemplate.inputs ?? {}), ...encryptedInputs }
            mappings = actionTemplate.mappings ?? undefined
        }

        const template = await this.hogFunctionTemplateManager.getHogFunctionTemplate(catalogTemplateId)

        if (!template) {
            throw new Error(`Template '${catalogTemplateId}' not found`)
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
