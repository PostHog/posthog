import { calculateCost, convertHogToJS, exec, ExecOptions, ExecResult } from '@posthog/hogvm'
import crypto from 'crypto'
import { DateTime } from 'luxon'
import { Histogram } from 'prom-client'
import RE2 from 're2'

import { buildIntegerMatcher } from '../config/config'
import { Hub, ValueMatcher } from '../types'
import { status } from '../utils/status'
import { HogFunctionManager } from './hog-function-manager'
import {
    HogFunctionInvocation,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionInvocationResult,
    HogFunctionQueueParametersFetchResponse,
    HogFunctionType,
} from './types'
import { buildExportedFunctionInvoker, convertToHogFunctionFilterGlobal } from './utils'

export const MAX_ASYNC_STEPS = 5
export const MAX_HOG_LOGS = 25
export const MAX_LOG_LENGTH = 10000
export const DEFAULT_TIMEOUT_MS = 100

const hogExecutionDuration = new Histogram({
    name: 'cdp_hog_function_execution_duration_ms',
    help: 'Processing time and success status of internal functions',
    // We have a timeout so we don't need to worry about much more than that
    buckets: [0, 10, 20, 50, 100, 200],
})

const hogFunctionFilterDuration = new Histogram({
    name: 'cdp_hog_function_filter_duration_ms',
    help: 'Processing time for filtering a function',
    // We have a timeout so we don't need to worry about much more than that
    buckets: [0, 10, 20, 50, 100, 200],
})

const hogFunctionStateMemory = new Histogram({
    name: 'cdp_hog_function_execution_state_memory_kb',
    help: 'The amount of memory in kb used by a hog function',
    buckets: [0, 50, 100, 250, 500, 1000, 2000, 3000, 5000, Infinity],
})

export function execHog(bytecode: any, options?: ExecOptions): ExecResult {
    return exec(bytecode, {
        timeout: DEFAULT_TIMEOUT_MS,
        maxAsyncSteps: 0,
        ...options,
        external: {
            regex: { match: (regex, str) => new RE2(regex).test(str) },
            crypto,
            ...(options?.external ?? {}),
        },
    })
}

export const formatInput = (bytecode: any, globals: HogFunctionInvocation['globals'], key?: string): any => {
    // Similar to how we generate the bytecode by iterating over the values,
    // here we iterate over the object and replace the bytecode with the actual values
    // bytecode is indicated as an array beginning with ["_H"] (versions 1+) or ["_h"] (version 0)

    if (Array.isArray(bytecode) && (bytecode[0] === '_h' || bytecode[0] === '_H')) {
        const res = execHog(bytecode, { globals })
        if (res.error) {
            throw res.error
        }
        if (!res.finished) {
            // NOT ALLOWED
            throw new Error(`Could not execute bytecode for input field: ${key}`)
        }
        return convertHogToJS(res.result)
    }

    if (Array.isArray(bytecode)) {
        return bytecode.map((item) => formatInput(item, globals, key))
    } else if (typeof bytecode === 'object') {
        return Object.fromEntries(
            Object.entries(bytecode).map(([key2, value]) => [
                key2,
                formatInput(value, globals, key ? `${key}.${key2}` : key2),
            ])
        )
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
    private telemetryMatcher: ValueMatcher<number>

    constructor(private hub: Hub, private hogFunctionManager: HogFunctionManager) {
        this.telemetryMatcher = buildIntegerMatcher(this.hub.CDP_HOG_FILTERS_TELEMETRY_TEAMS, true)
    }

    findMatchingFunctions(event: HogFunctionInvocationGlobals): {
        matchingFunctions: HogFunctionType[]
        nonMatchingFunctions: HogFunctionType[]
        erroredFunctions: HogFunctionType[]
    } {
        const allFunctionsForTeam = this.hogFunctionManager.getTeamHogDestinations(event.project.id)
        const filtersGlobals = convertToHogFunctionFilterGlobal(event)

        const nonMatchingFunctions: HogFunctionType[] = []
        const matchingFunctions: HogFunctionType[] = []
        const erroredFunctions: HogFunctionType[] = []

        // Filter all functions based on the invocation
        allFunctionsForTeam.forEach((hogFunction) => {
            if (hogFunction.filters?.bytecode) {
                const start = performance.now()
                try {
                    const filterResult = execHog(hogFunction.filters.bytecode, {
                        globals: filtersGlobals,
                        telemetry: this.telemetryMatcher(hogFunction.team_id),
                    })
                    if (typeof filterResult.result === 'boolean' && filterResult.result) {
                        matchingFunctions.push(hogFunction)
                        return
                    }
                    if (filterResult.error) {
                        status.error('🦔', `[HogExecutor] Error filtering function`, {
                            hogFunctionId: hogFunction.id,
                            hogFunctionName: hogFunction.name,
                            teamId: hogFunction.team_id,
                            error: filterResult.error.message,
                            result: filterResult,
                        })
                        erroredFunctions.push(hogFunction)
                        return
                    }
                } catch (error) {
                    status.error('🦔', `[HogExecutor] Error filtering function`, {
                        hogFunctionId: hogFunction.id,
                        hogFunctionName: hogFunction.name,
                        teamId: hogFunction.team_id,
                        error: error.message,
                    })
                    erroredFunctions.push(hogFunction)
                    return
                } finally {
                    const duration = performance.now() - start
                    hogFunctionFilterDuration.observe(performance.now() - start)

                    if (duration > DEFAULT_TIMEOUT_MS) {
                        status.error('🦔', `[HogExecutor] Filter took longer than expected`, {
                            hogFunctionId: hogFunction.id,
                            hogFunctionName: hogFunction.name,
                            teamId: hogFunction.team_id,
                            duration,
                            eventId: event.event.uuid,
                        })
                    }
                }
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
            erroredFunctions,
        }
    }

    execute(invocation: HogFunctionInvocation): HogFunctionInvocationResult {
        const loggingContext = {
            invocationId: invocation.id,
            hogFunctionId: invocation.hogFunction.id,
            hogFunctionName: invocation.hogFunction.name,
            hogFunctionUrl: invocation.globals.source?.url,
        }

        status.debug('🦔', `[HogExecutor] Executing function`, loggingContext)

        const result: HogFunctionInvocationResult = {
            invocation,
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
            // If the queueParameter is set then we have an expected format that we want to parse and add to the stack
            if (invocation.queueParameters) {
                // NOTE: This is all based around the only response type being fetch currently
                const {
                    logs = [],
                    response = null,
                    error,
                    timings = [],
                } = invocation.queueParameters as HogFunctionQueueParametersFetchResponse
                // Reset the queue parameters to be sure
                invocation.queue = 'hog'
                invocation.queueParameters = undefined

                const status = typeof response?.status === 'number' ? response.status : 503

                // Special handling for fetch
                if (status >= 400) {
                    // Generic warn log for bad status codes
                    logs.push({
                        level: 'warn',
                        timestamp: DateTime.now(),
                        message: `Fetch returned bad status: ${status}`,
                    })
                }

                if (!invocation.vmState) {
                    throw new Error("VM state wasn't provided for queue parameters")
                }

                if (error) {
                    throw new Error(error)
                }

                if (typeof response?.body === 'string') {
                    try {
                        response.body = JSON.parse(response.body)
                    } catch (e) {
                        // pass - if it isn't json we just pass it on
                    }
                }

                // Finally we create the response object as the VM expects
                invocation.vmState!.stack.push({
                    status,
                    body: response?.body,
                })
                invocation.timings = invocation.timings.concat(timings)
                result.logs = [...logs, ...result.logs]
            }

            const start = performance.now()
            let globals: HogFunctionInvocationGlobalsWithInputs
            let execRes: ExecResult | undefined = undefined

            try {
                globals = this.buildHogFunctionGlobals(invocation)
            } catch (e) {
                result.logs.push({
                    level: 'error',
                    timestamp: DateTime.now(),
                    message: `Error building inputs: ${e}`,
                })

                throw e
            }

            const sensitiveValues = this.getSensitiveValues(invocation.hogFunction, globals.inputs)
            const invocationInput =
                invocation.vmState ??
                (invocation.functionToExecute
                    ? buildExportedFunctionInvoker(
                          invocation.hogFunction.bytecode,
                          globals,
                          invocation.functionToExecute[0], // name
                          invocation.functionToExecute[1] // args
                      )
                    : invocation.hogFunction.bytecode)

            try {
                let hogLogs = 0
                execRes = execHog(invocationInput, {
                    globals: invocation.functionToExecute ? undefined : globals,
                    maxAsyncSteps: MAX_ASYNC_STEPS, // NOTE: This will likely be configurable in the future
                    asyncFunctions: {
                        // We need to pass these in but they don't actually do anything as it is a sync exec
                        fetch: async () => Promise.resolve(),
                    },
                    importBytecode: (module) => {
                        // TODO: more than one hardcoded module
                        if (module === 'provider/email') {
                            const provider = this.hogFunctionManager.getTeamHogEmailProvider(invocation.teamId)
                            if (!provider) {
                                throw new Error('No email provider configured')
                            }
                            try {
                                const providerGlobals = this.buildHogFunctionGlobals({
                                    id: '',
                                    teamId: invocation.teamId,
                                    hogFunction: provider,
                                    globals: {} as any,
                                    queue: 'hog',
                                    timings: [],
                                    priority: 0,
                                } satisfies HogFunctionInvocation)

                                return {
                                    bytecode: provider.bytecode,
                                    globals: providerGlobals,
                                }
                            } catch (e) {
                                result.logs.push({
                                    level: 'error',
                                    timestamp: DateTime.now(),
                                    message: `Error building inputs: ${e}`,
                                })
                                throw e
                            }
                        }
                        throw new Error(`Can't import unknown module: ${module}`)
                    },
                    functions: {
                        print: (...args) => {
                            hogLogs++
                            if (hogLogs === MAX_HOG_LOGS) {
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
                if (execRes.error) {
                    throw execRes.error
                }
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
            result.invocation.vmState = execRes.state
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
                    switch (execRes.asyncFunctionName) {
                        case 'fetch':
                            // Sanitize the args
                            const [url, fetchOptions] = args as [string | undefined, Record<string, any> | undefined]

                            if (typeof url !== 'string') {
                                throw new Error('fetch: Invalid URL')
                            }

                            const method = fetchOptions?.method || 'POST'
                            const headers = fetchOptions?.headers || {
                                'Content-Type': 'application/json',
                            }
                            // Modify the body to ensure it is a string (we allow Hog to send an object to keep things simple)
                            const body: string | undefined = fetchOptions?.body
                                ? typeof fetchOptions.body === 'string'
                                    ? fetchOptions.body
                                    : JSON.stringify(fetchOptions.body)
                                : fetchOptions?.body

                            result.invocation.queue = 'fetch'
                            result.invocation.queueParameters = {
                                url,
                                method,
                                body,
                                headers,
                                return_queue: 'hog',
                            }
                            break
                        default:
                            throw new Error(`Unknown async function '${execRes.asyncFunctionName}'`)
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
                    messages.push(`Event: '${globals.event.url}'`)

                    hogFunctionStateMemory.observe(execRes.state.maxMemUsed / 1024)

                    if (execRes.state.maxMemUsed > 1024 * 1024) {
                        // If the memory used is more than a MB then we should log it
                        status.warn('🦔', `[HogExecutor] Function used more than 1MB of memory`, {
                            hogFunctionId: invocation.hogFunction.id,
                            hogFunctionName: invocation.hogFunction.name,
                            teamId: invocation.teamId,
                            eventId: invocation.globals.event.url,
                            memoryUsedKb: execRes.state.maxMemUsed / 1024,
                        })
                    }
                }
                result.logs.push({
                    level: 'debug',
                    timestamp: DateTime.now(),
                    message: messages.join(' '),
                })
            }
        } catch (err) {
            result.error = err.message
            result.finished = true // Explicitly set to true to prevent infinite loops
            status.error(
                '🦔',
                `[HogExecutor] Error executing function ${invocation.hogFunction.id} - ${invocation.hogFunction.name}. Event: '${invocation.globals.event?.url}'`,
                err
            )
        }

        return result
    }

    buildHogFunctionGlobals(invocation: HogFunctionInvocation): HogFunctionInvocationGlobalsWithInputs {
        const builtInputs: Record<string, any> = {}

        Object.entries(invocation.hogFunction.inputs ?? {}).forEach(([key, item]) => {
            builtInputs[key] = item.value

            if (item.bytecode) {
                // Use the bytecode to compile the field
                builtInputs[key] = formatInput(item.bytecode, invocation.globals, key)
            }
        })

        Object.entries(invocation.hogFunction.encrypted_inputs ?? {}).forEach(([key, item]) => {
            builtInputs[key] = item.value

            if (item.bytecode) {
                // Use the bytecode to compile the field
                builtInputs[key] = formatInput(item.bytecode, invocation.globals, key)
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
