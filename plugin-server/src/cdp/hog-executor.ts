import { calculateCost, convertHogToJS, exec, ExecResult } from '@posthog/hogvm'
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
    HogFunctionType,
} from './types'
import { convertToHogFunctionFilterGlobal } from './utils'

const MAX_ASYNC_STEPS = 2
const MAX_HOG_LOGS = 10
const MAX_LOG_LENGTH = 10000
export const DEFAULT_TIMEOUT_MS = 100

const hogExecutionDuration = new Histogram({
    name: 'cdp_hog_function_execution_duration_ms',
    help: 'Processing time and success status of internal functions',
    // We have a timeout so we don't need to worry about much more than that
    buckets: [0, 10, 20, 50, 100, 200],
})

export const formatInput = (bytecode: any, globals: HogFunctionInvocation['globals']): any => {
    // Similar to how we generate the bytecode by iterating over the values,
    // here we iterate over the object and replace the bytecode with the actual values
    // bytecode is indicated as an array beginning with ["_H"] (versions 1+) or ["_h"] (version 0)

    if (Array.isArray(bytecode) && (bytecode[0] === '_h' || bytecode[0] === '_H')) {
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
                // TODO: This should be reported as a log or metric
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
            timings: [],
        })
    }

    /**
     * Intended to be invoked as a continuation from an async function
     */
    executeAsyncResponse(
        invocation: HogFunctionInvocation,
        asyncFunctionResponse: HogFunctionInvocationAsyncResponse['asyncFunctionResponse']
    ): HogFunctionInvocationResult {
        if (!invocation.hogFunctionId) {
            throw new Error('No hog function id provided')
        }

        const { logs = [], response = null, error: asyncError, timings = [] } = asyncFunctionResponse

        if (response?.status && response.status >= 400) {
            // Generic warn log for bad status codes
            logs.push({
                level: 'warn',
                timestamp: DateTime.now(),
                message: `Fetch returned bad status: ${response.status}`,
            })
        }

        const errorRes = (error = 'Something went wrong'): HogFunctionInvocationResult => ({
            invocation,
            finished: false,
            error,
            logs: [
                ...logs,
                {
                    level: 'error',
                    timestamp: DateTime.now(),
                    message: error,
                },
            ],
        })

        const hogFunction = this.hogFunctionManager.getTeamHogFunction(
            invocation.globals.project.id,
            invocation.hogFunctionId
        )

        if (!hogFunction || !invocation.vmState || asyncError) {
            return errorRes(
                !hogFunction
                    ? `Hog Function with ID ${invocation.hogFunctionId} not found`
                    : asyncError
                    ? asyncError
                    : 'No VM state provided for async response'
            )
        }

        if (typeof response?.body === 'string') {
            try {
                response.body = JSON.parse(response.body)
            } catch (e) {
                // pass - if it isn't json we just pass it on
            }
        }

        // Add the response to the stack to continue execution
        invocation.vmState.stack.push(response)
        invocation.timings.push(...timings)

        const res = this.execute(hogFunction, invocation)

        // Add any timings and logs from the async function
        res.logs = [...(logs ?? []), ...res.logs]

        return res
    }

    execute(hogFunction: HogFunctionType, invocation: HogFunctionInvocation): HogFunctionInvocationResult {
        const loggingContext = {
            hogFunctionId: hogFunction.id,
            hogFunctionName: hogFunction.name,
            hogFunctionUrl: invocation.globals.source?.url,
        }

        status.debug('🦔', `[HogExecutor] Executing function`, loggingContext)

        const result: HogFunctionInvocationResult = {
            invocation,
            asyncFunctionRequest: undefined,
            finished: false,
            capturedPostHogEvents: [],
            logs: [],
        }

        result.logs.push({
            level: 'debug',
            timestamp: DateTime.now(),
            message: invocation.vmState ? 'Resuming function' : `Executing function`,
        })

        try {
            const start = performance.now()
            let globals: HogFunctionInvocationGlobalsWithInputs
            let execRes: ExecResult | undefined = undefined

            try {
                globals = this.buildHogFunctionGlobals(hogFunction, invocation)
            } catch (e) {
                result.logs.push({
                    level: 'error',
                    timestamp: DateTime.now(),
                    message: `Error building inputs: ${e}`,
                })

                throw e
            }

            const sensitiveValues = this.getSensitiveValues(hogFunction, globals.inputs)

            try {
                let hogLogs = 0
                execRes = exec(invocation.vmState ?? hogFunction.bytecode, {
                    globals,
                    timeout: DEFAULT_TIMEOUT_MS,
                    maxAsyncSteps: MAX_ASYNC_STEPS, // NOTE: This will likely be configurable in the future
                    asyncFunctions: {
                        // We need to pass these in but they don't actually do anything as it is a sync exec
                        fetch: async () => Promise.resolve(),
                    },
                    functions: {
                        print: (...args) => {
                            hogLogs++
                            if (hogLogs == MAX_HOG_LOGS) {
                                result.logs.push({
                                    level: 'warn',
                                    timestamp: DateTime.now(),
                                    message: `Function exceeded maximum log entries. No more logs will be collected.`,
                                })
                            }

                            if (hogLogs >= MAX_HOG_LOGS) {
                                return
                            }

                            result.logs.push({
                                level: 'info',
                                timestamp: DateTime.now(),
                                message: sanitizeLogMessage(args, sensitiveValues),
                            })
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
                                result.logs.push({
                                    level: 'warn',
                                    timestamp: DateTime.now(),
                                    message: `postHogCapture was called from an event that already executed this function. To prevent infinite loops, the event was not captured.`,
                                })
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
                result.logs.push({
                    level: 'error',
                    timestamp: DateTime.now(),
                    message: `Error executing function: ${e}`,
                })
                throw e
            }

            const duration = performance.now() - start
            hogExecutionDuration.observe(duration)

            result.finished = execRes.finished
            invocation.timings.push({
                kind: 'hog',
                duration_ms: duration,
            })

            if (!execRes.finished) {
                const args = (execRes.asyncFunctionArgs ?? []).map((arg) => convertHogToJS(arg))
                if (!execRes.state) {
                    // NOTE: This shouldn't be possible so is more of a type sanity check
                    throw new Error('State should be provided for async function')
                }
                result.logs.push({
                    level: 'debug',
                    timestamp: DateTime.now(),
                    message: `Suspending function due to async function call '${execRes.asyncFunctionName}'. Payload: ${
                        calculateCost(execRes.state) + calculateCost(args)
                    } bytes`,
                })

                if (execRes.asyncFunctionName) {
                    result.invocation.vmState = execRes.state
                    result.asyncFunctionRequest = {
                        name: execRes.asyncFunctionName,
                        args: args,
                    }
                } else {
                    result.logs.push({
                        level: 'warn',
                        timestamp: DateTime.now(),
                        message: `Function was not finished but also had no async function to execute.`,
                    })
                }
            } else {
                const totalDuration = invocation.timings.reduce((acc, timing) => acc + timing.duration_ms, 0)
                const messages = [`Function completed in ${totalDuration}ms.`]
                if (execRes.state) {
                    messages.push(`Sync: ${execRes.state.syncDuration}ms.`)
                    messages.push(`Mem: ${execRes.state.maxMemUsed} bytes.`)
                    messages.push(`Ops: ${execRes.state.ops}.`)
                }
                result.logs.push({
                    level: 'debug',
                    timestamp: DateTime.now(),
                    message: messages.join(' '),
                })
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
                        if (typeof val === 'string') {
                            values.push(val)
                        }
                    })
                }
            }
        })

        return values
    }
}
