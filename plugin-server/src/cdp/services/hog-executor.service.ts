import { calculateCost, convertHogToJS, exec, ExecOptions, ExecResult } from '@posthog/hogvm'
import crypto from 'crypto'
import { DateTime } from 'luxon'
import { Histogram } from 'prom-client'
import RE2 from 're2'

import { buildIntegerMatcher } from '../../config/config'
import { PluginsServerConfig, ValueMatcher } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { UUIDT } from '../../utils/utils'
import {
    CyclotronFetchFailureInfo,
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionFilterGlobals,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionQueueParametersFetchRequest,
    HogFunctionQueueParametersFetchResponse,
    HogFunctionType,
    LogEntry,
    MinimalAppMetric,
} from '../types'
import { convertToHogFunctionFilterGlobal } from '../utils'
import { filterFunctionInstrumented } from '../utils/hog-function-filtering'
import { createInvocation, createInvocationResult } from '../utils/invocation-utils'
import { LiquidRenderer } from '../utils/liquid'

export const MAX_ASYNC_STEPS = 5
export const MAX_HOG_LOGS = 25
export const MAX_LOG_LENGTH = 10000
export const DEFAULT_TIMEOUT_MS = 100

export const EXTEND_OBJECT_KEY = '$$_extend_object'

const hogExecutionDuration = new Histogram({
    name: 'cdp_hog_function_execution_duration_ms',
    help: 'Processing time and success status of internal functions',
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

export const formatHogInput = (bytecode: any, globals: HogFunctionInvocationGlobalsWithInputs, key?: string): any => {
    // Similar to how we generate the bytecode by iterating over the values,
    // here we iterate over the object and replace the bytecode with the actual values
    // bytecode is indicated as an array beginning with ["_H"] (versions 1+) or ["_h"] (version 0)

    if (bytecode === null || bytecode === undefined) {
        return bytecode // Preserve null and undefined values
    }

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
        return bytecode.map((item) => formatHogInput(item, globals, key))
    } else if (typeof bytecode === 'object' && bytecode !== null) {
        let ret: Record<string, any> = {}

        if (bytecode[EXTEND_OBJECT_KEY]) {
            const res = formatHogInput(bytecode[EXTEND_OBJECT_KEY], globals, key)
            if (res && typeof res === 'object') {
                ret = {
                    ...res,
                }
            }
        }

        for (const [subkey, value] of Object.entries(bytecode)) {
            if (subkey === EXTEND_OBJECT_KEY) {
                continue
            }
            ret[subkey] = formatHogInput(value, globals, key ? `${key}.${subkey}` : subkey)
        }

        return ret
    } else {
        return bytecode
    }
}

const formatLiquidInput = (value: unknown, globals: HogFunctionInvocationGlobalsWithInputs, key?: string): any => {
    if (value === null || value === undefined) {
        return value
    }

    if (typeof value === 'string') {
        return LiquidRenderer.renderWithHogFunctionGlobals(value, globals)
    }

    if (Array.isArray(value)) {
        return value.map((item) => formatLiquidInput(item, globals, key))
    }

    if (typeof value === 'object' && value !== null) {
        return Object.fromEntries(
            Object.entries(value).map(([key2, value]) => [
                key2,
                formatLiquidInput(value, globals, key ? `${key}.${key2}` : key2),
            ])
        )
    }

    return value
}

export const sanitizeLogMessage = (args: any[], sensitiveValues?: string[]): string => {
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
        return (input1?.order ?? -1) - (input2?.order ?? -1)
    })

    for (const [key, input] of orderedInputs) {
        if (!input) {
            continue
        }

        newGlobals.inputs[key] = input.value

        const templating = input.templating ?? 'hog'

        if (templating === 'liquid') {
            newGlobals.inputs[key] = formatLiquidInput(input.value, newGlobals, key)
        } else if (templating === 'hog' && input?.bytecode) {
            newGlobals.inputs[key] = formatHogInput(input.bytecode, newGlobals, key)
        }
    }

    return newGlobals
}

export class HogExecutorService {
    private telemetryMatcher: ValueMatcher<number>

    constructor(private config: PluginsServerConfig) {
        this.telemetryMatcher = buildIntegerMatcher(this.config.CDP_HOG_FILTERS_TELEMETRY_TEAMS, true)
    }

    buildHogFunctionInvocations(
        hogFunctions: HogFunctionType[],
        triggerGlobals: HogFunctionInvocationGlobals
    ): {
        invocations: CyclotronJobInvocationHogFunction[]
        metrics: MinimalAppMetric[]
        logs: LogEntry[]
    } {
        const metrics: MinimalAppMetric[] = []
        const logs: LogEntry[] = []
        const invocations: CyclotronJobInvocationHogFunction[] = []

        // TRICKY: The frontend generates filters matching the Clickhouse event type so we are converting back
        const filterGlobals: HogFunctionFilterGlobals = convertToHogFunctionFilterGlobal(triggerGlobals)

        const _filterHogFunction = (
            hogFunction: HogFunctionType,
            filters: HogFunctionType['filters'],
            filterGlobals: HogFunctionFilterGlobals
        ) => {
            const filterResults = filterFunctionInstrumented({
                fn: hogFunction,
                filters,
                filterGlobals,
                eventUuid: triggerGlobals.event.uuid,
                enabledTelemetry: this.telemetryMatcher(hogFunction.team_id),
            })

            // Add any generated metrics and logs to our collections
            metrics.push(...filterResults.metrics)
            logs.push(...filterResults.logs)

            return filterResults.match
        }

        const _buildInvocation = (
            hogFunction: HogFunctionType,
            inputs: HogFunctionType['inputs']
        ): CyclotronJobInvocationHogFunction | null => {
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
        invocation: CyclotronJobInvocationHogFunction,
        options: { functions?: Record<string, (args: unknown[]) => unknown> } = {}
    ): CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> {
        const loggingContext = {
            invocationId: invocation.id,
            hogFunctionId: invocation.hogFunction.id,
            hogFunctionName: invocation.hogFunction.name,
            hogFunctionUrl: invocation.state.globals.source?.url,
        }

        logger.debug('🦔', `[HogExecutor] Executing function`, loggingContext)

        const result = createInvocationResult<CyclotronJobInvocationHogFunction>(invocation, {
            queue: 'hog',
        })

        result.logs.push({
            level: 'debug',
            timestamp: DateTime.now(),
            message: invocation.state.vmState ? 'Resuming function' : `Executing function`,
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

                if (!invocation.state.vmState) {
                    throw new Error("VM state wasn't provided for queue parameters")
                }

                if (error) {
                    throw new Error(error)
                }

                if (typeof body === 'string') {
                    try {
                        body = parseJSON(body)
                    } catch (e) {
                        // pass - if it isn't json we just pass it on
                    }
                }

                // Finally we create the response object as the VM expects
                result.invocation.state.vmState!.stack.push({
                    status,
                    body: body,
                })
                result.invocation.state.timings = result.invocation.state.timings.concat(timings)
                result.logs = [...logs, ...result.logs]
            }

            const start = performance.now()
            let globals: HogFunctionInvocationGlobalsWithInputs
            let execRes: ExecResult | undefined = undefined

            try {
                // NOTE: As of the mappings work, we added input generation to the caller, reducing the amount of data passed into the function
                // This is just a fallback to support the old format - once fully migrated we can remove the building and just use the globals
                if (invocation.state.globals.inputs) {
                    globals = invocation.state.globals
                } else {
                    const inputs: HogFunctionType['inputs'] = {
                        ...(invocation.hogFunction.inputs ?? {}),
                        ...(invocation.hogFunction.encrypted_inputs ?? {}),
                    }
                    globals = buildGlobalsWithInputs(invocation.state.globals, inputs)
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
            const invocationInput = invocation.state.vmState ?? invocation.hogFunction.bytecode
            const eventId = invocation?.state.globals?.event?.uuid || 'Unknown event'

            try {
                let hogLogs = 0

                execRes = execHog(invocationInput, {
                    globals,
                    timeout: this.config.CDP_WATCHER_HOG_COST_TIMING_UPPER_MS,
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
                            const distinctId = event.distinct_id || globals.event?.distinct_id
                            const eventName = event.event
                            const eventProperties = event.properties || {}

                            if (typeof event.event !== 'string') {
                                throw new Error("[HogFunction] - postHogCapture call missing 'event' property")
                            }

                            if (!distinctId) {
                                throw new Error("[HogFunction] - postHogCapture call missing 'distinct_id' property")
                            }

                            if (result.capturedPostHogEvents.length > 0) {
                                throw new Error(
                                    'postHogCapture was called more than once. Only one call is allowed per function'
                                )
                            }

                            if (globals.event) {
                                // Protection to stop a recursive loop
                                const givenCount = globals.event.properties?.$hog_function_execution_count
                                const executionCount = typeof givenCount === 'number' ? givenCount : 0

                                if (executionCount > 0) {
                                    result.logs.push({
                                        level: 'warn',
                                        timestamp: DateTime.now(),
                                        message: `postHogCapture was called from an event that already executed this function. To prevent infinite loops, the event was not captured.`,
                                    })
                                    return
                                }

                                // Increment the execution count so that we can check it in the future
                                eventProperties.$hog_function_execution_count = executionCount + 1
                            }

                            result.capturedPostHogEvents.push({
                                team_id: invocation.teamId,
                                timestamp: DateTime.utc().toISO(),
                                distinct_id: distinctId,
                                event: eventName,
                                properties: {
                                    ...eventProperties,
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
            result.invocation.state.vmState = execRes.state
            result.invocation.state.timings.push({
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
                        case 'fetch': {
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

                            const fetchQueueParameters = this.enrichFetchRequest({
                                url,
                                method,
                                body,
                                headers,
                                return_queue: 'hog',
                            })

                            result.invocation.queue = 'fetch'
                            result.invocation.queueParameters = fetchQueueParameters
                            break
                        }
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
                const totalDuration = result.invocation.state.timings.reduce(
                    (acc, timing) => acc + timing.duration_ms,
                    0
                )
                const messages = [`Function completed in ${totalDuration}ms.`]
                if (execRes.state) {
                    messages.push(`Sync: ${execRes.state.syncDuration}ms.`)
                    messages.push(`Mem: ${execRes.state.maxMemUsed} bytes.`)
                    messages.push(`Ops: ${execRes.state.ops}.`)
                    messages.push(`Event: '${globals.event.url}'`)

                    hogFunctionStateMemory.observe(execRes.state.maxMemUsed / 1024)

                    if (execRes.state.maxMemUsed > 1024 * 1024) {
                        // If the memory used is more than a MB then we should log it
                        logger.warn('🦔', `[HogExecutor] Function used more than 1MB of memory`, {
                            hogFunctionId: invocation.hogFunction.id,
                            hogFunctionName: invocation.hogFunction.name,
                            teamId: invocation.teamId,
                            eventId: invocation.state.globals.event.url,
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
            logger.error(
                '🦔',
                `[HogExecutor] Error executing function ${invocation.hogFunction.id} - ${invocation.hogFunction.name}. Event: '${invocation.state.globals.event?.url}'`,
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

    public enrichFetchRequest(request: HogFunctionQueueParametersFetchRequest): HogFunctionQueueParametersFetchRequest {
        // TRICKY: Some 3rd parties require developer tokens to be passed in the headers
        // We don't want to expose these to the user so we add them here out of the custom code loop

        request.headers = request.headers ?? {}

        if (request.url.startsWith('https://googleads.googleapis.com/') && !request.headers['developer-token']) {
            request.headers['developer-token'] = this.config.CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN
        }

        return request
    }

    public redactFetchRequest(request: HogFunctionQueueParametersFetchRequest): HogFunctionQueueParametersFetchRequest {
        if (request.headers && request.headers['developer-token'] === this.config.CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN) {
            delete request.headers['developer-token']
        }

        return request
    }
}

function fetchFailureToLogMessage(failure: CyclotronFetchFailureInfo): string {
    return `Fetch failure of kind ${failure.kind} with status ${failure.status ?? '(none)'} and message ${
        failure.message
    }`
}
