import { convertHogToJS, convertJSToHog, exec, ExecResult, VMState } from '@posthog/hogvm'
import { DateTime } from 'luxon'
import { Histogram } from 'prom-client'

import { status } from '../utils/status'
import { UUIDT } from '../utils/utils'
import { HogFunctionManager } from './hog-function-manager'
import {
    HogFunctionInvocation,
    HogFunctionInvocationAsyncResponse,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionInvocationResult,
    HogFunctionLogEntryLevel,
    HogFunctionType,
} from './types'
import { convertToHogFunctionFilterGlobal } from './utils'

const MAX_ASYNC_STEPS = 2
const MAX_HOG_LOGS = 10
const MAX_LOG_LENGTH = 10000
const DEFAULT_TIMEOUT_MS = 100

const hogExecutionDuration = new Histogram({
    name: 'cdp_hog_function_execution_duration_ms',
    help: 'Processing time and success status of internal functions',
    // We have a timeout so we don't need to worry about much more than that
    buckets: [0, 10, 20, 50, 100, 200],
})

export const formatInput = (bytecode: any, globals: HogFunctionInvocation['globals']): any => {
    // Similar to how we generate the bytecode by iterating over the values,
    // here we iterate over the object and replace the bytecode with the actual values
    // bytecode is indicated as an array beginning with ["_h"]

    if (Array.isArray(bytecode) && bytecode[0] === '_h') {
        const res = exec(bytecode, {
            globals,
            timeout: DEFAULT_TIMEOUT_MS,
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

const sanitizeLogMessage = (args: any[], sensitiveValues?: string[]): string => {
    let message = args.map((arg) => (typeof arg !== 'string' ? JSON.stringify(arg) : arg)).join(', ')

    // Find and replace any sensitive values
    sensitiveValues?.forEach((sensitiveValue) => {
        message = message.replaceAll(sensitiveValue, '***REDACTED***')
    })

    if (message.length > MAX_LOG_LENGTH) {
        message = message.slice(0, MAX_LOG_LENGTH) + '... (truncated)'
    }

    return message
}

export class HogExecutor {
    constructor(private hogFunctionManager: HogFunctionManager) {}

    findMatchingFunctions(event: HogFunctionInvocationGlobals): {
        matchingFunctions: HogFunctionType[]
        nonMatchingFunctions: HogFunctionType[]
    } {
        const allFunctionsForTeam = this.hogFunctionManager.getTeamHogFunctions(event.project.id)
        const filtersGlobals = convertToHogFunctionFilterGlobal(event)

        const nonMatchingFunctions: HogFunctionType[] = []
        const matchingFunctions: HogFunctionType[] = []

        // Filter all functions based on the invocation
        allFunctionsForTeam.forEach((hogFunction) => {
            try {
                if (hogFunction.filters?.bytecode) {
                    const filterResult = exec(hogFunction.filters.bytecode, {
                        globals: filtersGlobals,
                        timeout: DEFAULT_TIMEOUT_MS,
                        maxAsyncSteps: 0,
                    })

                    if (typeof filterResult.result === 'boolean' && filterResult.result) {
                        matchingFunctions.push(hogFunction)
                        return
                    }
                }
            } catch (error) {
                status.error('🦔', `[HogExecutor] Error filtering function`, {
                    hogFunctionId: hogFunction.id,
                    hogFunctionName: hogFunction.name,
                    error: error.message,
                })
            }

            nonMatchingFunctions.push(hogFunction)
        })

        status.debug(
            '🦔',
            `[HogExecutor] Found ${Object.keys(matchingFunctions).length} matching functions out of ${
                Object.keys(allFunctionsForTeam).length
            } for team`
        )

        return {
            nonMatchingFunctions,
            matchingFunctions,
        }
    }

    /**
     * Intended to be invoked as a starting point from an event
     */
    executeFunction(
        event: HogFunctionInvocationGlobals,
        functionOrId: HogFunctionType | HogFunctionType['id']
    ): HogFunctionInvocationResult | undefined {
        const hogFunction =
            typeof functionOrId === 'string'
                ? this.hogFunctionManager.getTeamHogFunction(event.project.id, functionOrId)
                : functionOrId

        if (!hogFunction) {
            return
        }

        // Add the source of the trigger to the globals
        const modifiedGlobals: HogFunctionInvocationGlobals = {
            ...event,
            source: {
                name: hogFunction.name ?? `Hog function: ${hogFunction.id}`,
                url: `${event.project.url}/pipeline/destinations/hog-${hogFunction.id}/configuration/`,
            },
        }

        return this.execute(hogFunction, {
            id: new UUIDT().toString(),
            globals: modifiedGlobals,
            teamId: hogFunction.team_id,
            hogFunctionId: hogFunction.id,
            logs: [],
            timings: [],
        })
    }

    /**
     * Intended to be invoked as a continuation from an async function
     */
    executeAsyncResponse(invocation: HogFunctionInvocationAsyncResponse): HogFunctionInvocationResult {
        if (!invocation.hogFunctionId) {
            throw new Error('No hog function id provided')
        }

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

        const hogFunction = this.hogFunctionManager.getTeamHogFunction(
            invocation.globals.project.id,
            invocation.hogFunctionId
        )

        if (!hogFunction) {
            return errorRes(`Hog Function with ID ${invocation.hogFunctionId} not found`)
        }

        const { vmState } = invocation.asyncFunctionRequest ?? {}
        const { asyncFunctionResponse } = invocation

        if (!vmState || !asyncFunctionResponse.response || asyncFunctionResponse.error) {
            return errorRes(invocation.error ?? 'No VM state provided for async response')
        }

        // Add the response to the stack to continue execution
        vmState.stack.push(convertJSToHog(asyncFunctionResponse.response ?? null))

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

        status.debug('🦔', `[HogExecutor] Executing function`, loggingContext)

        const result: HogFunctionInvocationResult = {
            ...invocation,
            asyncFunctionRequest: undefined,
            finished: false,
            capturedPostHogEvents: [],
        }

        if (!state) {
            addLog(result, 'debug', `Executing function`)
        } else {
            addLog(result, 'debug', `Resuming function`)
        }

        try {
            const start = performance.now()
            let globals: HogFunctionInvocationGlobalsWithInputs
            let execRes: ExecResult | undefined = undefined

            try {
                globals = this.buildHogFunctionGlobals(hogFunction, invocation)
            } catch (e) {
                addLog(result, 'error', `Error building inputs: ${e}`)
                throw e
            }

            const sensitiveValues = this.getSensitiveValues(hogFunction, globals.inputs)

            try {
                let hogLogs = 0
                execRes = exec(state ?? hogFunction.bytecode, {
                    globals,
                    timeout: DEFAULT_TIMEOUT_MS, // TODO: Swap this to milliseconds when the package is updated
                    maxAsyncSteps: MAX_ASYNC_STEPS, // NOTE: This will likely be configurable in the future
                    asyncFunctions: {
                        // We need to pass these in but they don't actually do anything as it is a sync exec
                        fetch: async () => Promise.resolve(),
                    },
                    functions: {
                        print: (...args) => {
                            hogLogs++
                            if (hogLogs == MAX_HOG_LOGS) {
                                addLog(
                                    result,
                                    'warn',
                                    `Function exceeded maximum log entries. No more logs will be collected.`
                                )
                            }

                            if (hogLogs >= MAX_HOG_LOGS) {
                                return
                            }

                            addLog(result, 'info', sanitizeLogMessage(args, sensitiveValues))
                        },
                        postHogCapture: (event) => {
                            if (typeof event.event !== 'string') {
                                throw new Error("[HogFunction] - postHogCapture call missing 'event' property")
                            }

                            if (result.capturedPostHogEvents!.length > 0) {
                                throw new Error(
                                    'postHogCapture was called more than once. Only one call is allowed per function'
                                )
                            }
                            const executionCount = globals.event.properties?.$hog_function_execution_count ?? 0

                            if (executionCount > 0) {
                                addLog(
                                    result,
                                    'warn',
                                    `postHogCapture was called from an event that already executed this function. To prevent infinite loops, the event was not captured.`
                                )
                                return
                            }

                            result.capturedPostHogEvents!.push({
                                team_id: invocation.teamId,
                                timestamp: DateTime.utc().toISO(),
                                distinct_id: event.distinct_id || invocation.globals.event.distinct_id,
                                event: event.event,
                                properties: {
                                    ...event.properties,
                                    // Increment the execution count so that we can check it in the future
                                    $hog_function_execution_count: executionCount + 1,
                                },
                            })
                        },
                    },
                })
            } catch (e) {
                addLog(result, 'error', `Error executing function: ${e}`)
                throw e
            }

            const duration = performance.now() - start
            hogExecutionDuration.observe(duration)

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

    buildHogFunctionGlobals(
        hogFunction: HogFunctionType,
        invocation: HogFunctionInvocation
    ): HogFunctionInvocationGlobalsWithInputs {
        const builtInputs: Record<string, any> = {}

        Object.entries(hogFunction.inputs ?? {}).forEach(([key, item]) => {
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

    getSensitiveValues(hogFunction: HogFunctionType, inputs: Record<string, any>): string[] {
        const values: string[] = []

        hogFunction.inputs_schema?.forEach((schema) => {
            if (schema.secret || schema.type === 'integration') {
                const value = inputs[schema.key]
                if (typeof value === 'string') {
                    values.push(value)
                } else if (
                    (schema.type === 'dictionary' || schema.type === 'integration') &&
                    typeof value === 'object'
                ) {
                    // Assume the values are the sensitive parts
                    Object.values(value).forEach((val: any) => {
                        values.push(val)
                    })
                }
            }
        })

        return values
    }
}
