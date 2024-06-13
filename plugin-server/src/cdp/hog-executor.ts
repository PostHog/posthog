import { convertHogToJS, convertJSToHog, exec, VMState } from '@posthog/hogvm'
import { DateTime } from 'luxon'

import { PluginsServerConfig, TimestampFormat } from '../types'
import { status } from '../utils/status'
import { castTimestampOrNow, UUIDT } from '../utils/utils'
import { AsyncFunctionExecutor } from './async-function-executor'
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
        private asyncFunctionExecutor: AsyncFunctionExecutor
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
                        maxAsyncSteps: 2, // Current limit - allows most needs such as a GET before a POST
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
    async executeAsyncResponse(invocation: HogFunctionInvocationAsyncResponse): Promise<HogFunctionInvocationResult> {
        if (!invocation.hogFunctionId) {
            throw new Error('No hog function id provided')
        }

        // TODO: The VM takes care of ensuring we don't get stuck in a loop but we should add some extra protection
        // to be super sure

        const hogFunction = this.hogFunctionManager.getTeamHogFunctions(invocation.globals.project.id)[
            invocation.hogFunctionId
        ]

        if (!invocation.vmState || invocation.error) {
            // TODO: Maybe add a log as well?
            return {
                ...invocation,
                success: false,
                error: invocation.error ?? new Error('No VM state provided for async response'),
                logs: [],
            }
        }
        invocation.vmState.stack.push(convertJSToHog(invocation.vmResponse ?? null))

        return await this.execute(hogFunction, invocation, invocation.vmState)
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
        let lastTimestamp = DateTime.now()

        const log = (level: HogFunctionLogEntryLevel, message: string) => {
            // TRICKY: The log entries table is de-duped by timestamp, so we need to ensure that the timestamps are unique
            // It is unclear how this affects parallel execution environments
            let now = DateTime.now()
            if (now <= lastTimestamp) {
                // Ensure that the timestamps are unique
                now = lastTimestamp.plus(1)
            }
            lastTimestamp = now

            logs.push({
                team_id: hogFunction.team_id,
                log_source: 'hog_function',
                log_source_id: hogFunction.id,
                instance_id: invocation.id,
                timestamp: castTimestampOrNow(now, TimestampFormat.ClickHouse),
                level,
                message,
            })
        }

        if (!state) {
            log('debug', `Executing function`)
        } else {
            log('debug', `Resuming function`)
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
                    print: (...args) => {
                        const message = args
                            .map((arg) => (typeof arg !== 'string' ? JSON.stringify(arg) : arg))
                            .join(', ')
                        log('info', message)
                    },
                },
            })

            if (!res.finished) {
                log('debug', `Suspending function due to async function call '${res.asyncFunctionName}'`)
                status.info('🦔', `[HogExecutor] Function returned not finished. Executing async function`, {
                    ...loggingContext,
                    asyncFunctionName: res.asyncFunctionName,
                })

                const args = (res.asyncFunctionArgs ?? []).map((arg) => convertHogToJS(arg))

                if (res.asyncFunctionName) {
                    await this.asyncFunctionExecutor.execute({
                        ...invocation,
                        teamId: hogFunction.team_id,
                        hogFunctionId: hogFunction.id,
                        asyncFunctionName: res.asyncFunctionName,
                        asyncFunctionArgs: args,
                        vmState: res.state,
                    })
                } else {
                    log('warn', `Function was not finished but also had no async function to execute.`)
                }
            } else {
                log('debug', `Function completed`)
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
}
