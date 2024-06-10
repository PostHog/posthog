import { exec, ExecResult, VMState } from '@posthog/hogvm'
import { Webhook } from '@posthog/plugin-scaffold'
import { PluginsServerConfig } from 'types'

import { trackedFetch } from '../utils/fetch'
import { status } from '../utils/status'
import { RustyHook } from '../worker/rusty-hook'
import { HogFunctionManager } from './hog-function-manager'
import {
    HogFunctionInvocation,
    HogFunctionInvocationAsyncResponse,
    HogFunctionInvocationContext,
    HogFunctionType,
} from './types'

export const formatInput = (bytecode: any, globals: HogFunctionInvocation['globals']): any => {
    // Similar to how we generate the bytecode by iterating over the values,
    // here we iterate over the object and replace the bytecode with the actual values
    // bytecode is indicated as an array beginning with ["_h"]

    if (Array.isArray(bytecode) && bytecode[0] === '_h') {
        const res = exec(bytecode, {
            globals,
            timeout: 100,
            maxAsyncSteps: 0,
        })

        if (!res.finished) {
            // NOT ALLOWED
            throw new Error('Input fields must be simple sync values')
        }
        return res.result
    }

    if (Array.isArray(bytecode)) {
        return bytecode.map((item) => formatInput(item, globals))
    } else if (typeof bytecode === 'object') {
        return Object.fromEntries(Object.entries(bytecode).map(([key, value]) => [key, formatInput(value, globals)]))
    } else {
        return bytecode
    }
}

export class HogExecutor {
    constructor(
        private serverConfig: PluginsServerConfig,
        private hogFunctionManager: HogFunctionManager,
        private rustyHook: RustyHook
    ) {}

    /**
     * Intended to be invoked as a starting point from an event
     */
    async executeMatchingFunctions(invocation: HogFunctionInvocation): Promise<any> {
        let functions = this.hogFunctionManager.getTeamHogFunctions(invocation.globals.project.id)

        // Filter all functions based on the invocation
        functions = Object.fromEntries(
            Object.entries(functions).filter(([_key, value]) => {
                try {
                    const filters = value.filters

                    if (!filters?.bytecode) {
                        // NOTE: If we don't have bytecode this indicates something went wrong.
                        // The model will always safe a bytecode if it was compiled correctly
                        return false
                    }

                    const filterResult = exec(filters.bytecode, {
                        globals: invocation.globals,
                        timeout: 100,
                        maxAsyncSteps: 0,
                    })

                    if (typeof filterResult.result !== 'boolean') {
                        // NOTE: If the result is not a boolean we should not execute the function
                        return false
                    }

                    return filterResult.result
                } catch (error) {
                    status.error('🦔', `[HogExecutor] Error filtering function`, {
                        hogFunctionId: value.id,
                        hogFunctionName: value.name,
                        error: error.message,
                    })
                }

                return false
            })
        )

        if (!Object.keys(functions).length) {
            return
        }

        for (const hogFunction of Object.values(functions)) {
            // Add the source of the trigger to the globals
            const modifiedGlobals: HogFunctionInvocationContext = {
                ...invocation.globals,
                source: {
                    name: hogFunction.name ?? `Hog function: ${hogFunction.id}`,
                    url: `${invocation.globals.project.url}/pipeline/destinations/hog-${hogFunction.id}/configuration/`,
                },
            }

            await this.execute(hogFunction, {
                ...invocation,
                globals: modifiedGlobals,
            })
        }
    }

    /**
     * Intended to be invoked as a continuation from an async function
     */
    async executeAsyncResponse(invocation: HogFunctionInvocationAsyncResponse): Promise<any> {
        if (!invocation.hogFunctionId) {
            throw new Error('No hog function id provided')
        }

        const hogFunction = this.hogFunctionManager.getTeamHogFunctions(invocation.globals.project.id)[
            invocation.hogFunctionId
        ]

        invocation.vmState.stack.push(invocation.response)

        await this.execute(hogFunction, invocation, invocation.vmState)
    }

    async execute(hogFunction: HogFunctionType, invocation: HogFunctionInvocation, state?: VMState): Promise<any> {
        const loggingContext = {
            hogFunctionId: hogFunction.id,
            hogFunctionName: hogFunction.name,
            hogFunctionUrl: invocation.globals.source?.url,
        }

        status.info('🦔', `[HogExecutor] Executing function`, loggingContext)

        try {
            const globals = this.buildHogFunctionGlobals(hogFunction, invocation)

            const res = exec(state ?? hogFunction.bytecode, {
                globals,
                timeout: 100, // NOTE: This will likely be configurable in the future
                maxAsyncSteps: 5, // NOTE: This will likely be configurable in the future
                asyncFunctions: {
                    // We need to pass these in but they don't actually do anything as it is a sync exec
                    fetch: async () => Promise.resolve(),
                },
            })

            console.log('🦔', `[HogExecutor] TESTING`, {
                asyncFunctionArgs: res.asyncFunctionArgs,
                asyncFunctionName: res.asyncFunctionName,
                globals: globals,
            })

            if (!res.finished) {
                status.info('🦔', `[HogExecutor] Function returned not finished. Executing async function`, {
                    ...loggingContext,
                    asyncFunctionName: res.asyncFunctionName,
                })
                switch (res.asyncFunctionName) {
                    case 'fetch':
                        await this.asyncFunctionFetch(hogFunction, invocation, res)
                        break
                    default:
                        status.error(
                            '🦔',
                            `[HogExecutor] Unknown async function: ${res.asyncFunctionName}`,
                            loggingContext
                        )
                    // TODO: Log error somewhere
                }
            }
        } catch (error) {
            status.error('🦔', `[HogExecutor] Error executing function ${hogFunction.id} - ${hogFunction.name}`, error)
        }
    }

    buildHogFunctionGlobals(hogFunction: HogFunctionType, invocation: HogFunctionInvocation): Record<string, any> {
        const builtInputs: Record<string, any> = {}

        Object.entries(hogFunction.inputs).forEach(([key, item]) => {
            // TODO: Replace this with iterator
            builtInputs[key] = item.value

            if (item.bytecode) {
                // Use the bytecode to compile the field
                builtInputs[key] = formatInput(item.bytecode, invocation.globals)
            }
        })

        return {
            ...invocation.globals,
            inputs: builtInputs,
        }
    }

    private async asyncFunctionFetch(
        hogFunction: HogFunctionType,
        invocation: HogFunctionInvocation,
        execResult: ExecResult
    ): Promise<any> {
        const SPECIAL_CONFIG_ID = -3 // Hardcoded to mean Hog

        // TODO: validate the args
        const args = execResult.asyncFunctionArgs ?? []
        const url: string = args[0]
        const options = Object.fromEntries(args[1].entries())

        const method = options.method || 'POST'
        const headers = options.headers || {
            'Content-Type': 'application/json',
        }
        const body = options.body || {}

        const webhook: Webhook = {
            url,
            method: method,
            headers: headers,
            body: typeof body === 'string' ? body : JSON.stringify(body, undefined, 4),
        }

        const success = await this.rustyHook.enqueueIfEnabledForTeam({
            webhook: webhook,
            teamId: hogFunction.team_id,
            pluginId: SPECIAL_CONFIG_ID,
            pluginConfigId: SPECIAL_CONFIG_ID,
        })

        // TODO: Temporary test code
        if (!success) {
            status.info('🦔', `[HogExecutor] Webhook not sent via rustyhook, sending directly instead`)
            const fetchResponse = await trackedFetch(url, {
                method: webhook.method,
                body: webhook.body,
                headers: webhook.headers,
                timeout: this.serverConfig.EXTERNAL_REQUEST_TIMEOUT_MS,
            })

            await this.executeAsyncResponse({
                ...invocation,
                hogFunctionId: hogFunction.id,
                vmState: execResult.state!,
                response: {
                    status: fetchResponse.status,
                    body: await fetchResponse.text(),
                },
            })
        }
    }
}
