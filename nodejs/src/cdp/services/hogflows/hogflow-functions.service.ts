import { HogFlow, HogFlowAction } from '~/cdp/schema/hogflow'
import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionType,
} from '~/cdp/types'

import { HogExecutorAsyncService, HogExecutorExecuteAsyncOptions } from '../hog-executor-async.service'
import { HogFunctionTemplateManagerService } from '../managers/hog-function-template-manager.service'
import { AcceptedSend } from './transactional-email'

type FunctionActionType = 'function' | 'function_email' | 'function_sms'
type Action = Extract<HogFlowAction, { type: FunctionActionType }>

const layAcceptedSendOver = (
    globals: HogFunctionInvocationGlobalsWithInputs,
    send: AcceptedSend
): HogFunctionInvocationGlobalsWithInputs => ({
    ...globals,
    inputs: {
        ...globals.inputs,
        email: {
            ...globals.inputs.email,
            ...(send.content && {
                subject: send.content.subject,
                html: send.content.html ?? '',
                text: send.content.text ?? '',
                preheader: '',
            }),
            ...(send.from && { from: { ...send.from } }),
            ...(send.replyTo && { replyTo: send.replyTo.join(', ') }),
        },
    },
})

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
            inputs,
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

    // `send` is laid over the inputs only when they are first rendered, so continuations reuse it. Its
    // capture choice goes on every build, because the email service reads it from the function's metadata.
    async buildHogFunctionInvocation(
        invocation: CyclotronJobInvocationHogFlow,
        hogFunction: HogFunctionType,
        globals: Omit<HogFunctionInvocationGlobals, 'source' | 'project'>,
        send?: AcceptedSend
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

        const hogFunctionInvocation: CyclotronJobInvocationHogFunction = {
            ...invocation,
            hogFunction: {
                ...hogFunction,
                metadata: { ...hogFunction.metadata, capture_engagement: send?.tracking.captureEngagement ?? null },
            },
            state: invocation.state.currentAction?.hogFunctionState ?? {
                globals: await this.buildInputsWithGlobals(hogFunction, globalsWithSource, send),
                timings: [],
                attempts: 0,
                actionId: invocation.state.currentAction?.id,
                actionStepCount: invocation.state.actionStepCount,
                customerTaskIdempotencyVersion: invocation.state.customerTaskIdempotencyVersion,
                rerunAttempts: invocation.state.rerunAttempts,
            },
        }

        return hogFunctionInvocation
    }

    private async buildInputsWithGlobals(
        hogFunction: HogFunctionType,
        globals: HogFunctionInvocationGlobals,
        send?: AcceptedSend
    ): Promise<HogFunctionInvocationGlobalsWithInputs> {
        const rendered = await this.hogFunctionExecutor.hogExecutor.buildInputsWithGlobals(hogFunction, globals)
        return send ? layAcceptedSendOver(rendered, send) : rendered
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
