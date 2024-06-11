import { convertHogToJS, convertJSToHog, exec, ExecResult, VMState } from '@posthog/hogvm'
import { Webhook } from '@posthog/plugin-scaffold'
import { PluginsServerConfig } from 'types'

import { trackedFetch } from '../utils/fetch'
import { status } from '../utils/status'
import { UUIDT } from '../utils/utils'
import { RustyHook } from '../worker/rusty-hook'
import { HogFunctionManager } from './hog-function-manager'
import {
    HogFunctionInvocation,
    HogFunctionInvocationAsyncResponse,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationResult,
    HogFunctionLogEntry,
    HogFunctionLogEntryLevel,
    HogFunctionType,
} from './types'
import { convertToHogFunctionFilterGlobal } from './utils'

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
        return convertHogToJS(res.result)
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
    async executeMatchingFunctions(event: HogFunctionInvocationGlobals): Promise<HogFunctionInvocationResult[]> {
        const allFunctionsForTeam = this.hogFunctionManager.getTeamHogFunctions(event.project.id)

        const filtersGlobals = convertToHogFunctionFilterGlobal(event)

        // Filter all functions based on the invocation
        const functions = Object.fromEntries(
            Object.entries(allFunctionsForTeam).filter(([_key, value]) => {
                try {
                    const filters = value.filters

                    if (!filters?.bytecode) {
                        // NOTE: If we don't have bytecode this indicates something went wrong.
                        // The model will always save a bytecode if it was compiled correctly
                        return false
                    }

                    const filterResult = exec(filters.bytecode, {
                        globals: filtersGlobals,
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
            return []
        }

        status.info(
            '🦔',
            `[HogExecutor] Found ${Object.keys(functions).length} matching functions out of ${
                Object.keys(allFunctionsForTeam).length
            } for team`
        )

        const results: HogFunctionInvocationResult[] = []

        for (const hogFunction of Object.values(functions)) {
            // Add the source of the trigger to the globals
            const modifiedGlobals: HogFunctionInvocationGlobals = {
                ...event,
                source: {
                    name: hogFunction.name ?? `Hog function: ${hogFunction.id}`,
                    url: `${event.project.url}/pipeline/destinations/hog-${hogFunction.id}/configuration/`,
                },
            }

            const result = await this.execute(hogFunction, {
                id: new UUIDT().toString(),
                globals: modifiedGlobals,
            })

            results.push(result)
        }

        return results
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

        invocation.vmState.stack.push(convertJSToHog(invocation.response))

        await this.execute(hogFunction, invocation, invocation.vmState)
    }

    async execute(
        hogFunction: HogFunctionType,
        invocation: HogFunctionInvocation,
        state?: VMState
    ): Promise<HogFunctionInvocationResult> {
        const loggingContext = {
            hogFunctionId: hogFunction.id,
            hogFunctionName: hogFunction.name,
            hogFunctionUrl: invocation.globals.source?.url,
        }

        status.info('🦔', `[HogExecutor] Executing function`, loggingContext)

        let error: any = null
        const logs: HogFunctionLogEntry[] = []

        const log = (level: HogFunctionLogEntryLevel, message: string) => {
            logs.push({
                team_id: hogFunction.team_id,
                log_source: 'hog_function',
                log_source_id: hogFunction.id,
                instance_id: invocation.id,
                timestamp: new Date().toISOString(),
                level,
                message,
            })
        }

        if (!state) {
            log('info', `Executing function  (${hogFunction.id}) (${hogFunction.name})`)
        } else {
            log('info', `Resuming function  (${hogFunction.id}) (${hogFunction.name})`)
        }

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
                functions: {
                    print: (message: string, ...args) => {
                        status.info('🦔', '[HogExecutor] print', message, ...args)
                        log('info', message)
                    },
                },
            })

            if (!res.finished) {
                log('info', `Suspending function (${hogFunction.id}) (${hogFunction.name})`)
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
            } else {
                log('info', `Function completed (${hogFunction.id}) (${hogFunction.name})!`)
            }
        } catch (err) {
            error = err
            status.error('🦔', `[HogExecutor] Error executing function ${hogFunction.id} - ${hogFunction.name}`, error)
        }

        return {
            ...invocation,
            success: !error,
            error,
            logs,
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
        // TODO: validate the args
        const args = (execResult.asyncFunctionArgs ?? []).map((arg) => convertHogToJS(arg))
        const url: string = args[0]
        const options = args[1]

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

        // NOTE: Purposefully disabled for now - once we have callback support we can re-enable
        // const SPECIAL_CONFIG_ID = -3 // Hardcoded to mean Hog
        // const success = await this.rustyHook.enqueueIfEnabledForTeam({
        //     webhook: webhook,
        //     teamId: hogFunction.team_id,
        //     pluginId: SPECIAL_CONFIG_ID,
        //     pluginConfigId: SPECIAL_CONFIG_ID,
        // })

        const success = false

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
