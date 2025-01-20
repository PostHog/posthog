import { calculateCost, convertHogToJS, exec, ExecOptions, ExecResult } from '@posthog/hogvm'
import crypto from 'crypto'
import { DateTime } from 'luxon'
import { Histogram } from 'prom-client'
import RE2 from 're2'

import { buildIntegerMatcher } from '../config/config'
import { Hub, ValueMatcher } from '../types'
import { status } from '../utils/status'
import { UUIDT } from '../utils/utils'
import { HogFunctionManager } from './hog-function-manager'
import {
    CyclotronFetchFailureInfo,
    HogFunctionAppMetric,
    HogFunctionFilterGlobals,
    HogFunctionInvocation,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionInvocationLogEntry,
    HogFunctionInvocationResult,
    HogFunctionQueueParametersFetchResponse,
    HogFunctionType,
} from './types'
import { buildExportedFunctionInvoker, convertToHogFunctionFilterGlobal, createInvocation } from './utils'

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

export const buildGlobalsWithInputs = (
    globals: HogFunctionInvocationGlobals,
    inputs: HogFunctionType['inputs']
): HogFunctionInvocationGlobalsWithInputs => {
    const newGlobals: HogFunctionInvocationGlobalsWithInputs = {
        ...globals,
        inputs: {},
    }

    const orderedInputs = Object.entries(inputs ?? {}).sort(([_, input1], [__, input2]) => {
        return (input1.order ?? -1) - (input2.order ?? -1)
    })

    for (const [key, input] of orderedInputs) {
        newGlobals.inputs[key] = input.value

        if (input.bytecode) {
            // Use the bytecode to compile the field
            newGlobals.inputs[key] = formatInput(input.bytecode, newGlobals, key)
        }
    }

    return newGlobals
}

export class HogExecutor {
    private telemetryMatcher: ValueMatcher<number>

    constructor(private hub: Hub, private hogFunctionManager: HogFunctionManager) {
        this.telemetryMatcher = buildIntegerMatcher(this.hub.CDP_HOG_FILTERS_TELEMETRY_TEAMS, true)
    }

    findHogFunctionInvocations(triggerGlobals: HogFunctionInvocationGlobals) {
        // Build and generate invocations for all the possible mappings
        const allFunctionsForTeam = this.hogFunctionManager.getTeamHogFunctions(triggerGlobals.project.id)

        return this.buildHogFunctionInvocations(allFunctionsForTeam, triggerGlobals)
    }

    buildHogFunctionInvocations(
        hogFunctions: HogFunctionType[],
        triggerGlobals: HogFunctionInvocationGlobals
    ): {
        invocations: HogFunctionInvocation[]
        metrics: HogFunctionAppMetric[]
        logs: HogFunctionInvocationLogEntry[]
    } {
        const metrics: HogFunctionAppMetric[] = []
        const logs: HogFunctionInvocationLogEntry[] = []
        const invocations: HogFunctionInvocation[] = []

        // TRICKY: The frontend generates filters matching the Clickhouse event type so we are converting back
        const filterGlobals = convertToHogFunctionFilterGlobal(triggerGlobals)

        const _filterHogFunction = (
            hogFunction: HogFunctionType,
            filters: HogFunctionType['filters'],
            filterGlobals: HogFunctionInvocationGlobals | HogFunctionFilterGlobals
        ) => {
            if (filters?.bytecode) {
                const start = performance.now()
                try {
                    const filterResult = execHog(filters.bytecode, {
                        globals: filterGlobals,
                        telemetry: this.telemetryMatcher(hogFunction.team_id),
                    })
                    if (filterResult.error) {
                        status.error('🦔', `[HogExecutor] Error filtering function`, {
                            hogFunctionId: hogFunction.id,
                            hogFunctionName: hogFunction.name,
                            teamId: hogFunction.team_id,
                            error: filterResult.error.message,
                            result: filterResult,
                        })

                        throw new Error(`${filterResult.error.message}`)
                    }

                    const result = typeof filterResult.result === 'boolean' && filterResult.result

                    if (!result) {
                        metrics.push({
                            team_id: hogFunction.team_id,
                            app_source_id: hogFunction.id,
                            metric_kind: 'other',
                            metric_name: 'filtered',
                            count: 1,
                        })
                    }

                    return result
                } catch (error) {
                    status.error('🦔', `[HogExecutor] Error filtering function`, {
                        hogFunctionId: hogFunction.id,
                        hogFunctionName: hogFunction.name,
                        teamId: hogFunction.team_id,
                        error: error.message,
                    })

                    metrics.push({
                        team_id: hogFunction.team_id,
                        app_source_id: hogFunction.id,
                        metric_kind: 'other',
                        metric_name: 'filtering_failed',
                        count: 1,
                    })

                    logs.push({
                        team_id: hogFunction.team_id,
                        log_source: 'hog_function',
                        log_source_id: hogFunction.id,
                        instance_id: new UUIDT().toString(), // random UUID, like it would be for an invocation
                        timestamp: DateTime.now(),
                        level: 'error',
                        message: `Error filtering event ${triggerGlobals.event.uuid}: ${error.message}`,
                    })
                    return false
                } finally {
                    const duration = performance.now() - start
                    hogFunctionFilterDuration.observe(performance.now() - start)

                    if (duration > DEFAULT_TIMEOUT_MS) {
                        status.error('🦔', `[HogExecutor] Filter took longer than expected`, {
                            hogFunctionId: hogFunction.id,
                            hogFunctionName: hogFunction.name,
                            teamId: hogFunction.team_id,
                            duration,
                            eventId: triggerGlobals.event.uuid,
                        })
                    }
                }
            }
        }

        const _buildInvocation = (
            hogFunction: HogFunctionType,
            inputs: HogFunctionType['inputs']
        ): HogFunctionInvocation | null => {
            try {
                const globalsWithSource = {
                    ...triggerGlobals,
                    source: {
                        name: hogFunction.name ?? `Hog function: ${hogFunction.id}`,
                        url: `${triggerGlobals.project.url}/pipeline/destinations/hog-${hogFunction.id}/configuration/`,
                    },
                }

                const globalsWithInputs = buildGlobalsWithInputs(globalsWithSource, inputs)

                return createInvocation(globalsWithInputs, hogFunction)
            } catch (error) {
                logs.push({
                    team_id: hogFunction.team_id,
                    log_source: 'hog_function',
                    log_source_id: hogFunction.id,
                    instance_id: new UUIDT().toString(), // random UUID, like it would be for an invocation
                    timestamp: DateTime.now(),
                    level: 'error',
                    message: `Error building inputs for event ${triggerGlobals.event.uuid}: ${error.message}`,
                })

                metrics.push({
                    team_id: hogFunction.team_id,
                    app_source_id: hogFunction.id,
                    metric_kind: 'failure',
                    metric_name: 'inputs_failed',
                    count: 1,
                })

                return null
            }
        }

        hogFunctions.forEach((hogFunction) => {
            // Check for non-mapping functions first
            if (!hogFunction.mappings) {
                if (!_filterHogFunction(hogFunction, hogFunction.filters, filterGlobals)) {
                    return
                }
                const invocation = _buildInvocation(hogFunction, {
                    ...(hogFunction.inputs ?? {}),
                    ...(hogFunction.encrypted_inputs ?? {}),
                })
                if (!invocation) {
                    return
                }

                invocations.push(invocation)
                return
            }

            hogFunction.mappings.forEach((mapping) => {
                // For mappings we want to match against both the mapping filters and the global filters
                if (
                    !_filterHogFunction(hogFunction, hogFunction.filters, filterGlobals) ||
                    !_filterHogFunction(hogFunction, mapping.filters, filterGlobals)
                ) {
                    return
                }

                const invocation = _buildInvocation(hogFunction, {
                    ...(hogFunction.inputs ?? {}),
                    ...(hogFunction.encrypted_inputs ?? {}),
                    ...(mapping.inputs ?? {}),
                })
                if (!invocation) {
                    return
                }

                invocations.push(invocation)
            })
        })

        return {
            invocations,
            metrics,
            logs,
        }
    }

    execute(
        invocation: HogFunctionInvocation,
        options: { functions?: Record<string, (args: unknown[]) => unknown> } = {}
    ): HogFunctionInvocationResult {
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
                    trace = [],
                    error,
                    timings = [],
                } = invocation.queueParameters as HogFunctionQueueParametersFetchResponse

                let body = invocation.queueParameters.body
                // Reset the queue parameters to be sure
                invocation.queue = 'hog'
                invocation.queueParameters = undefined

                // If we got a response from fetch, we know the response code was in the <300 range,
                // but if we didn't (indicating a bug in the fetch worker), we use a default of 503
                let status = response?.status ?? 503

                // If we got a trace, then the last "result" is the final attempt, and we should try to grab a status from it
                // or any preceding attempts, and produce a log message for each of them
                if (trace.length > 0) {
                    logs.push({
                        level: 'error',
                        timestamp: DateTime.now(),
                        message: `Fetch failed after ${trace.length} attempts`,
                    })
                    for (const attempt of trace) {
                        logs.push({
                            level: 'warn',
                            timestamp: DateTime.now(),
                            message: fetchFailureToLogMessage(attempt),
                        })
                        if (attempt.status) {
                            status = attempt.status
                        }
                    }
                }

                if (!invocation.vmState) {
                    throw new Error("VM state wasn't provided for queue parameters")
                }

                if (error) {
                    throw new Error(error)
                }

                if (typeof body === 'string') {
                    try {
                        body = JSON.parse(body)
                    } catch (e) {
                        // pass - if it isn't json we just pass it on
                    }
                }

                // Finally we create the response object as the VM expects
                invocation.vmState!.stack.push({
                    status,
                    body: body,
                })
                invocation.timings = invocation.timings.concat(timings)
                result.logs = [...logs, ...result.logs]
            }

            const start = performance.now()
            let globals: HogFunctionInvocationGlobalsWithInputs
            let execRes: ExecResult | undefined = undefined

            try {
                // NOTE: As of the mappings work, we added input generation to the caller, reducing the amount of data passed into the function
                // This is just a fallback to support the old format - once fully migrated we can remove the building and just use the globals
                if (invocation.globals.inputs) {
                    globals = invocation.globals
                } else {
                    const inputs: HogFunctionType['inputs'] = {
                        ...(invocation.hogFunction.inputs ?? {}),
                        ...(invocation.hogFunction.encrypted_inputs ?? {}),
                    }
                    globals = buildGlobalsWithInputs(invocation.globals, inputs)
                }
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

            const eventId = invocation?.globals?.event?.uuid || 'Unknown event'

            try {
                let hogLogs = 0

                execRes = execHog(invocationInput, {
                    globals: invocation.functionToExecute ? undefined : globals,
                    maxAsyncSteps: MAX_ASYNC_STEPS, // NOTE: This will likely be configurable in the future
                    asyncFunctions: {
                        // We need to pass these in but they don't actually do anything as it is a sync exec
                        fetch: async () => Promise.resolve(),
                    },
                    functions: {
                        print: (...args) => {
                            hogLogs++
                            if (hogLogs === MAX_HOG_LOGS) {
                                result.logs.push({
                                    level: 'warn',
                                    timestamp: DateTime.now(),
                                    message: `Function exceeded maximum log entries. No more logs will be collected. Event: ${eventId}`,
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
                        ...(options.functions ?? {}),
                    },
                })
                if (execRes.error) {
                    throw execRes.error
                }

                // Store the result if execution finished
                if (execRes.finished && execRes.result !== undefined) {
                    result.execResult = convertHogToJS(execRes.result)
                }
            } catch (e) {
                result.logs.push({
                    level: 'error',
                    timestamp: DateTime.now(),
                    message: `Error executing function on event ${eventId}: ${e}`,
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
                    } bytes. Event: ${eventId}`,
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

        // We don't want to add "REDACTED" for empty strings
        return values.filter((v) => v.trim())
    }
}

function fetchFailureToLogMessage(failure: CyclotronFetchFailureInfo): string {
    return `Fetch failure of kind ${failure.kind} with status ${failure.status} and message ${failure.message}`
}
