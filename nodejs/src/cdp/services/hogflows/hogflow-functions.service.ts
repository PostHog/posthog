import { CyclotronInputType } from '~/cdp/schema/cyclotron'
import { HogFlow, HogFlowAction } from '~/cdp/schema/hogflow'
import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInputSchemaType,
    HogFunctionInvocationGlobals,
    HogFunctionType,
} from '~/cdp/types'

import { HogExecutorAsyncService, HogExecutorExecuteAsyncOptions } from '../hog-executor-async.service'
import { HogFunctionTemplateManagerService } from '../managers/hog-function-template-manager.service'

type FunctionActionType = 'function' | 'function_email' | 'function_sms'
type Action = Extract<HogFlowAction, { type: FunctionActionType }>

// Helper class that can turn a hog flow action into a hog function
export class HogFlowFunctionsService {
    constructor(
        private siteUrl: string,
        private hogFunctionTemplateManager: HogFunctionTemplateManagerService,
        private hogFunctionExecutor: HogExecutorAsyncService
    ) {}

    async buildHogFunction(
        hogFlow: HogFlow,
        configuration: Action['config'],
        actionName?: string
    ): Promise<HogFunctionType> {
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
            inputs: bindTemplateSecrets(inputs, template.inputs_schema),
            inputs_schema: template.inputs_schema,
            template_id: template.template_id,
            mappings,
            created_at: '',
            updated_at: '',
            // The action's config, plus flow-level send settings the email service needs at the
            // send choke point, where only the synthetic hog function is in scope.
            metadata: {
                ...config,
                hog_flow_name: hogFlow.name,
                hog_flow_action_name: actionName ?? null,
                email_sending_rate_limit: hogFlow.email_sending_rate_limit ?? null,
                email_sending_paused_at: hogFlow.email_sending_paused_at ?? null,
                email_sending_paused_reason: hogFlow.email_sending_paused_reason ?? null,
                email_sending_paused_by: hogFlow.email_sending_paused_by ?? null,
            },
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
        globals: Omit<HogFunctionInvocationGlobals, 'source' | 'project'>,
        signal?: AbortSignal
    ): Promise<CyclotronJobInvocationHogFunction> {
        const teamId = invocation.hogFlow.team_id
        const projectUrl = `${this.siteUrl}/project/${teamId}`

        const globalsWithSource: HogFunctionInvocationGlobals = {
            ...globals,
            // Include workflow-level variables
            variables: invocation.state.variables,
            source: {
                id: invocation.hogFlow.id,
                name: invocation.hogFlow.name || `Hog flow: ${invocation.hogFlow.id}`,
                url: `${projectUrl}/workflows/${invocation.hogFlow.id}/workflow?node=${hogFunction.id}`,
            },
            project: {
                id: hogFunction.team_id,
                name: '',
                url: '',
            },
        }

        const savedState = invocation.state.currentAction?.hogFunctionState
        const functionState = savedState
            ? {
                  ...savedState,
                  renderedWorkflowVersion: savedState.renderedWorkflowVersion ?? invocation.hogFlow.version,
              }
            : {
                  globals: await this.hogFunctionExecutor.hogExecutor.buildInputsWithGlobals(
                      hogFunction,
                      globalsWithSource,
                      undefined,
                      {
                          appSourceId: invocation.parentRunId ?? invocation.hogFlow.id,
                          instanceId: invocation.state.currentAction?.id,
                          workflowId: invocation.hogFlow.id,
                          invocationId: invocation.id,
                          workflowVersion: invocation.hogFlow.version,
                      },
                      signal
                  ),
                  timings: [],
                  attempts: 0,
                  actionId: invocation.state.currentAction?.id,
                  actionStepCount: invocation.state.actionStepCount,
                  customerTaskIdempotencyVersion: invocation.state.customerTaskIdempotencyVersion,
                  rerunAttempts: invocation.state.rerunAttempts,
                  renderedWorkflowVersion: invocation.hogFlow.version,
              }

        const hogFunctionInvocation: CyclotronJobInvocationHogFunction = {
            ...invocation,
            hogFunction,
            state: { ...functionState, ...(invocation.state.send && { send: invocation.state.send }) },
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

// A workflow step runs its template's code and schema, which nobody can edit, so a secret takes its binding from there.
// A binding from a URL input would follow later edits of that input, so such a secret stays unbound.
function bindTemplateSecrets(
    inputs: HogFunctionType['inputs'],
    schemas: HogFunctionInputSchemaType[] | undefined
): HogFunctionType['inputs'] {
    if (!inputs) {
        return inputs
    }
    const bound = { ...inputs }
    for (const schema of schemas ?? []) {
        const input = Object.hasOwn(bound, schema.key) ? bound[schema.key] : null
        if (schema.secret && schema.auth?.origins && input) {
            const { origin_input: _originInput, ...declaration } = schema.auth
            bound[schema.key] = { ...input, auth: declaration } as CyclotronInputType
        }
    }
    return bound
}
