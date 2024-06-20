import { convertHogToJS, convertJSToHog, exec, ExecResult, VMState } from '@posthog/hogvm'
import { DateTime } from 'luxon'

import { PluginsServerConfig } from '../types'
import { status } from '../utils/status'
import { UUIDT } from '../utils/utils'
import { HogFunctionManager } from './hog-function-manager'
import {
    HogFunctionInvocation,
    HogFunctionInvocationAsyncResponse,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationResult,
    HogFunctionLogEntryLevel,
    HogFunctionType,
} from './types'
import { convertToHogFunctionFilterGlobal } from './utils'

const MAX_ASYNC_STEPS = 2

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

export const addLog = (result: HogFunctionInvocationResult, level: HogFunctionLogEntryLevel, message: string) => {
    const lastLog = result.logs[result.logs.length - 1]
    // TRICKY: The log entries table is de-duped by timestamp, so we need to ensure that the timestamps are unique
    // It is unclear how this affects parallel execution environments
    let now = DateTime.now()
    if (lastLog && now <= lastLog.timestamp) {
        // Ensure that the timestamps are unique
        now = lastLog.timestamp.plus(1)
    }

    result.logs.push({
        team_id: result.teamId,
        log_source: 'hog_function',
        log_source_id: result.hogFunctionId,
        instance_id: result.id,
        timestamp: now,
        level,
        message,
    })
}

export class HogExecutor {
    constructor(private serverConfig: PluginsServerConfig, private hogFunctionManager: HogFunctionManager) {}

    /**
     * Intended to be invoked as a starting point from an event
     */
    executeMatchingFunctions(event: HogFunctionInvocationGlobals): HogFunctionInvocationResult[] {
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

            const result = this.execute(hogFunction, {
                id: new UUIDT().toString(),
                globals: modifiedGlobals,
                teamId: hogFunction.team_id,
                hogFunctionId: hogFunction.id,
                logs: [],
                timings: [],
            })

            results.push(result)
        }

        return results
    }

    /**
     * Intended to be invoked as a continuation from an async function
     */
    executeAsyncResponse(invocation: HogFunctionInvocationAsyncResponse): HogFunctionInvocationResult {
        if (!invocation.hogFunctionId) {
            throw new Error('No hog function id provided')
        }

        // TODO: The VM takes care of ensuring we don't get stuck in a loop but we should add some extra protection
        // to be super sure

        const hogFunction = this.hogFunctionManager.getTeamHogFunctions(invocation.globals.project.id)[
            invocation.hogFunctionId
        ]

        const baseInvocation: HogFunctionInvocation = {
            id: invocation.id,
            globals: invocation.globals,
            teamId: invocation.teamId,
            hogFunctionId: invocation.hogFunctionId,
            timings: invocation.asyncFunctionResponse.timings,
            // Logs we always reset as we don't want to carry over logs between calls
            logs: [],
        }

        const errorRes = (error = 'Something went wrong'): HogFunctionInvocationResult => ({
            ...baseInvocation,
            finished: false,
            error,
        })

        if (!hogFunction) {
            return errorRes(`Hog Function with ID ${invocation.hogFunctionId} not found`)
        }

        const { vmState } = invocation.asyncFunctionRequest ?? {}
        const { asyncFunctionResponse } = invocation

        if (!vmState || !asyncFunctionResponse.vmResponse || asyncFunctionResponse.error) {
            return errorRes(invocation.error ?? 'No VM state provided for async response')
        }

        // Add the response to the stack to continue execution
        vmState.stack.push(convertJSToHog(asyncFunctionResponse.vmResponse ?? null))

        return this.execute(hogFunction, baseInvocation, vmState)
    }

    execute(
        hogFunction: HogFunctionType,
        invocation: HogFunctionInvocation,
        state?: VMState
    ): HogFunctionInvocationResult {
        const loggingContext = {
            hogFunctionId: hogFunction.id,
            hogFunctionName: hogFunction.name,
            hogFunctionUrl: invocation.globals.source?.url,
        }

        status.info('🦔', `[HogExecutor] Executing function`, loggingContext)

        const result: HogFunctionInvocationResult = {
            ...invocation,
            asyncFunctionRequest: undefined,
            finished: false,
        }

        if (!state) {
            addLog(result, 'debug', `Executing function`)
        } else {
            // NOTE: We do our own check here for async steps as it saves executing Hog and is easier to handle
            if (state.asyncSteps >= MAX_ASYNC_STEPS) {
                addLog(result, 'error', `Function exceeded maximum async steps`)
                result.error = 'Function exceeded maximum async steps'
                return result
            }
            addLog(result, 'debug', `Resuming function`)
        }

        try {
            const start = performance.now()
            let globals: Record<string, any> | undefined = undefined
            let execRes: ExecResult | undefined = undefined

            try {
                globals = this.buildHogFunctionGlobals(hogFunction, invocation)
            } catch (e) {
                addLog(result, 'error', `Error building inputs: ${e}`)
                throw e
            }

            try {
                execRes = exec(state ?? hogFunction.bytecode, {
                    globals,
                    timeout: 100, // NOTE: This will likely be configurable in the future
                    maxAsyncSteps: MAX_ASYNC_STEPS, // NOTE: This will likely be configurable in the future
                    asyncFunctions: {
                        // We need to pass these in but they don't actually do anything as it is a sync exec
                        fetch: async () => Promise.resolve(),
                    },
                    functions: {
                        print: (...args) => {
                            const message = args
                                .map((arg) => (typeof arg !== 'string' ? JSON.stringify(arg) : arg))
                                .join(', ')
                            addLog(result, 'info', message)
                        },
                    },
                })
            } catch (e) {
                addLog(result, 'error', `Error executing function: ${e}`)
                throw e
            }

            const duration = performance.now() - start

            result.finished = execRes.finished
            result.timings.push({
                kind: 'hog',
                duration_ms: duration,
            })

            if (!execRes.finished) {
                addLog(result, 'debug', `Suspending function due to async function call '${execRes.asyncFunctionName}'`)

                const args = (execRes.asyncFunctionArgs ?? []).map((arg) => convertHogToJS(arg))

                if (!execRes.state) {
                    // NOTE: This shouldn't be possible so is more of a type sanity check
                    throw new Error('State should be provided for async function')
                }
                if (execRes.asyncFunctionName) {
                    result.asyncFunctionRequest = {
                        name: execRes.asyncFunctionName,
                        args: args,
                        vmState: execRes.state,
                    }
                } else {
                    addLog(result, 'warn', `Function was not finished but also had no async function to execute.`)
                }
            } else {
                const totalDuration = result.timings.reduce((acc, timing) => acc + timing.duration_ms, 0)

                addLog(result, 'debug', `Function completed. Processing time ${totalDuration}ms`)
            }
        } catch (err) {
            result.error = err.message
            status.error('🦔', `[HogExecutor] Error executing function ${hogFunction.id} - ${hogFunction.name}`, err)
        }

        return result
    }

    buildHogFunctionGlobals(hogFunction: HogFunctionType, invocation: HogFunctionInvocation): Record<string, any> {
        const builtInputs: Record<string, any> = {}

        Object.entries(hogFunction.inputs).forEach(([key, item]) => {
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
