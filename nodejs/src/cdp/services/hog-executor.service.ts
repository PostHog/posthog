import { pickBy } from 'lodash'
import { DateTime } from 'luxon'
import { Counter, Histogram } from 'prom-client'

import { ExecResult, convertHogToJS } from '@posthog/hogvm'

import { instrumented } from '~/common/tracing/tracing-utils'
import { ACCESS_TOKEN_PLACEHOLDER } from '~/config/constants'
import {
    CyclotronInvocationQueueParametersEmailSchema,
    CyclotronInvocationQueueParametersFetchSchema,
} from '~/schema/cyclotron'
import { FetchOptions, FetchResponse, InvalidRequestError, SecureRequestError, fetch } from '~/utils/request'
import { tryCatch } from '~/utils/try-catch'

import { Hub } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { UUIDT } from '../../utils/utils'
import {
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionFilterGlobals,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionType,
    LogEntry,
    MinimalAppMetric,
    MinimalLogEntry,
} from '../types'
import { destinationE2eLagMsSummary } from '../utils'
import { createAddLogFunction, sanitizeLogMessage } from '../utils'
import { execHog } from '../utils/hog-exec'
import { convertToHogFunctionFilterGlobal, filterFunctionInstrumented } from '../utils/hog-function-filtering'
import { createInvocation, createInvocationResult } from '../utils/invocation-utils'
import { HogInputsService, HogInputsServiceHub } from './hog-inputs.service'
import { PushSubscriptionsManagerService } from './managers/push-subscriptions-manager.service'
import { EmailService, EmailServiceHub } from './messaging/email.service'
import { RecipientTokensService } from './messaging/recipient-tokens.service'

/** Narrowed config type for CDP fetch retry settings, used by destination executors */
export type CdpFetchConfig = Pick<Hub, 'CDP_FETCH_RETRIES' | 'CDP_FETCH_BACKOFF_BASE_MS' | 'CDP_FETCH_BACKOFF_MAX_MS'>

export type HogExecutorServiceHub = CdpFetchConfig &
    HogInputsServiceHub &
    EmailServiceHub &
    Pick<Hub, 'CDP_WATCHER_HOG_COST_TIMING_UPPER_MS' | 'CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN'>

const cdpHttpRequests = new Counter({
    name: 'cdp_http_requests',
    help: 'HTTP requests and their outcomes',
    labelNames: ['status', 'template_id'],
})

const cdpHttpRequestTiming = new Histogram({
    name: 'cdp_http_request_timing_ms',
    help: 'Timing of HTTP requests',
    buckets: [0, 10, 20, 50, 100, 200, 500, 1000, 2000, 3000, 5000, 10000],
})

const pushNotificationSentCounter = new Counter({
    name: 'push_notification_sent_total',
    help: 'Total number of push notifications successfully sent',
    labelNames: ['platform'],
})

export async function cdpTrackedFetch({
    url,
    fetchParams,
    templateId,
}: {
    url: string
    fetchParams: FetchOptions
    templateId: string
}): Promise<{ fetchError: Error | null; fetchResponse: FetchResponse | null; fetchDuration: number }> {
    const start = performance.now()
    const [fetchError, fetchResponse] = await tryCatch(async () => await fetch(url, fetchParams))
    const fetchDuration = performance.now() - start
    cdpHttpRequestTiming.observe(fetchDuration)
    cdpHttpRequests.inc({ status: fetchResponse?.status?.toString() ?? 'error', template_id: templateId })

    return { fetchError, fetchResponse, fetchDuration }
}

export const RETRIABLE_STATUS_CODES = [
    408, // Request Timeout
    429, // Too Many Requests (rate limiting)
    500, // Internal Server Error
    502, // Bad Gateway
    503, // Service Unavailable
    504, // Gateway Timeout
]

function formatNumber(val: number) {
    return Number(val.toPrecision(2)).toString()
}

export const isFetchResponseRetriable = (response: FetchResponse | null, error: any | null): boolean => {
    let canRetry = !!response?.status && RETRIABLE_STATUS_CODES.includes(response.status)

    if (error) {
        if (
            error instanceof SecureRequestError ||
            error instanceof InvalidRequestError ||
            error.name === 'ResponseContentLengthMismatchError'
        ) {
            canRetry = false
        } else {
            canRetry = true // Only retry on general errors, not security, validation, or response parsing errors
        }
    }

    return canRetry
}

export const getNextRetryTime = (backoffBaseMs: number, backoffMaxMs: number, tries: number): DateTime => {
    const backoffMs = Math.min(backoffBaseMs * tries + Math.floor(Math.random() * backoffBaseMs), backoffMaxMs)
    return DateTime.utc().plus({ milliseconds: backoffMs })
}

export const MAX_ASYNC_STEPS = 5
export const MAX_HOG_LOGS = 25
export const EXTEND_OBJECT_KEY = '$$_extend_object'

const hogExecutionDuration = new Histogram({
    name: 'cdp_hog_function_execution_duration_ms',
    help: 'Processing time and success status of internal functions',
    // We have a timeout so we don't need to worry about much more than that
    buckets: [0, 10, 20, 50, 100, 200, 300, 500, 1000],
})

const hogFunctionStateMemory = new Histogram({
    name: 'cdp_hog_function_execution_state_memory_kb',
    help: 'The amount of memory in kb used by a hog function',
    buckets: [0, 50, 100, 250, 500, 1000, 2000, 3000, 5000, Infinity],
})

export type HogExecutorExecuteOptions = {
    functions?: Record<string, (args: unknown[]) => unknown>
    asyncFunctionsNames?: ('fetch' | 'sendEmail')[]
}

export type HogExecutorExecuteAsyncOptions = HogExecutorExecuteOptions & {
    maxAsyncFunctions?: number
}

export class HogExecutorService {
    private hogInputsService: HogInputsService
    private emailService: EmailService
    private recipientTokensService: RecipientTokensService
    private pushSubscriptionsManager: PushSubscriptionsManagerService

    constructor(private hub: HogExecutorServiceHub) {
        this.recipientTokensService = new RecipientTokensService(hub)
        this.hogInputsService = new HogInputsService(hub)
        this.emailService = new EmailService(hub)
        this.pushSubscriptionsManager = new PushSubscriptionsManagerService(hub.postgres, hub.encryptedFields)
    }

    async buildInputsWithGlobals(
        hogFunction: HogFunctionType,
        globals: HogFunctionInvocationGlobals,
        additionalInputs?: Record<string, any>
    ): Promise<HogFunctionInvocationGlobalsWithInputs> {
        return this.hogInputsService.buildInputsWithGlobals(hogFunction, globals, additionalInputs)
    }

    async buildHogFunctionInvocations(
        hogFunctions: HogFunctionType[],
        triggerGlobals: HogFunctionInvocationGlobals
    ): Promise<{
        invocations: CyclotronJobInvocationHogFunction[]
        metrics: MinimalAppMetric[]
        logs: LogEntry[]
    }> {
        const metrics: MinimalAppMetric[] = []
        const logs: LogEntry[] = []
        const invocations: CyclotronJobInvocationHogFunction[] = []

        // TRICKY: The frontend generates filters matching the Clickhouse event type so we are converting back
        const filterGlobals = convertToHogFunctionFilterGlobal(triggerGlobals)

        const _filterHogFunction = async (
            hogFunction: HogFunctionType,
            filters: HogFunctionType['filters'],
            filterGlobals: HogFunctionFilterGlobals
        ): Promise<boolean> => {
            const filterResults = await filterFunctionInstrumented({
                fn: hogFunction,
                filters,
                filterGlobals,
            })

            // Add any generated metrics and logs to our collections
            metrics.push(...filterResults.metrics)
            logs.push(...filterResults.logs)

            return filterResults.match
        }

        const _buildInvocation = async (
            hogFunction: HogFunctionType,
            additionalInputs?: HogFunctionType['inputs']
        ): Promise<CyclotronJobInvocationHogFunction | null> => {
            try {
                const globalsWithSource = {
                    ...triggerGlobals,
                    source: {
                        name: hogFunction.name ?? `Hog function: ${hogFunction.id}`,
                        url: `${triggerGlobals.project.url}/pipeline/destinations/hog-${hogFunction.id}/configuration/`,
                    },
                }

                const globalsWithInputs = await this.hogInputsService.buildInputsWithGlobals(
                    hogFunction,
                    globalsWithSource,
                    additionalInputs
                )

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

        await Promise.all(
            hogFunctions.map(async (hogFunction) => {
                // We always check the top level filters
                if (!(await _filterHogFunction(hogFunction, hogFunction.filters, filterGlobals))) {
                    return
                }

                // Check for non-mapping functions first
                if (!hogFunction.mappings) {
                    const invocation = await _buildInvocation(hogFunction)
                    if (!invocation) {
                        return
                    }

                    invocations.push(invocation)
                    return
                }

                const mappingInvocations = await Promise.all(
                    hogFunction.mappings.map(async (mapping) => {
                        if (!(await _filterHogFunction(hogFunction, mapping.filters, filterGlobals))) {
                            return null
                        }

                        const invocation = await _buildInvocation(hogFunction, mapping.inputs ?? {})
                        return invocation
                    })
                )
                invocations.push(
                    ...mappingInvocations.filter((inv): inv is CyclotronJobInvocationHogFunction => inv !== null)
                )
            })
        )

        return {
            invocations,
            metrics,
            logs,
        }
    }

    @instrumented('hog-executor.executeWithAsyncFunctions')
    async executeWithAsyncFunctions(
        invocation: CyclotronJobInvocationHogFunction,
        options?: HogExecutorExecuteAsyncOptions
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        let asyncFunctionCount = 0
        const maxAsyncFunctions = options?.maxAsyncFunctions ?? 1

        let result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> | null = null
        const metrics: MinimalAppMetric[] = []
        const logs: MinimalLogEntry[] = []

        while (!result || !result.finished) {
            const nextInvocation: CyclotronJobInvocationHogFunction = result?.invocation ?? invocation

            const queueParamsType = nextInvocation.queueParameters?.type
            if (['fetch', 'email'].includes(queueParamsType ?? '')) {
                asyncFunctionCount++

                if (result && asyncFunctionCount > maxAsyncFunctions) {
                    // We don't want to block the consumer too much hence we have a limit on async functions
                    logger.debug('🦔', `[HogExecutor] Max async functions reached: ${maxAsyncFunctions}`)
                    break
                }

                if (queueParamsType === 'fetch') {
                    result = await this.executeFetch(nextInvocation)
                } else if (queueParamsType === 'email') {
                    result = await this.emailService.executeSendEmail(nextInvocation)
                } else {
                    throw new Error(`Unknown queue type: ${queueParamsType}`)
                }
            } else {
                // Finish execution, carrying forward previous execResult
                // Tricky: We don't pass metrics in previousResult as they're accumulated in the local metrics array
                const { metrics: _m, logs: _l, ...previousResultWithoutMetrics } = result || {}
                result = await this.execute(nextInvocation, options, previousResultWithoutMetrics)
            }

            logs.push(...result.logs)
            metrics.push(...result.metrics)

            // If we have finished _or_ something has been scheduled to run later _or_ we have reached the max async functions then we break the loop
            if (result.finished || result.invocation.queueScheduledAt) {
                break
            }
        }

        if (result.finished) {
            const capturedAt = invocation.state.globals.event?.captured_at
            if (capturedAt) {
                const e2eLagMs = Date.now() - new Date(capturedAt).getTime()
                destinationE2eLagMsSummary.observe(e2eLagMs)
            }
        }

        result.logs = logs
        result.metrics = metrics

        return result
    }

    @instrumented('hog-executor.execute')
    async execute(
        invocation: CyclotronJobInvocationHogFunction,
        options: HogExecutorExecuteOptions = {},
        previousResult: Pick<
            Partial<CyclotronJobInvocationResult>,
            'finished' | 'capturedPostHogEvents' | 'logs' | 'metrics' | 'error' | 'execResult'
        > = {}
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        const loggingContext = {
            invocationId: invocation.id,
            hogFunctionId: invocation.hogFunction.id,
            hogFunctionName: invocation.hogFunction.name,
            hogFunctionUrl: invocation.state.globals.source?.url,
        }

        logger.debug('🦔', `[HogExecutor] Executing function`, loggingContext)

        const result = createInvocationResult<CyclotronJobInvocationHogFunction>(invocation, {}, previousResult)
        const addLog = createAddLogFunction(result.logs)

        try {
            let globals: HogFunctionInvocationGlobalsWithInputs
            let execRes: ExecResult | undefined = undefined

            try {
                // NOTE: As of the mappings work, we added input generation to the caller, reducing the amount of data passed into the function
                // This is just a fallback to support the old format - once fully migrated we can remove the building and just use the globals
                if (invocation.state.globals.inputs) {
                    globals = invocation.state.globals
                } else {
                    globals = await this.hogInputsService.buildInputsWithGlobals(
                        invocation.hogFunction,
                        invocation.state.globals
                    )
                }
            } catch (e) {
                addLog('error', `Error building inputs: ${e}`)

                throw e
            }

            const sensitiveValues = this.getSensitiveValues(invocation.hogFunction, globals.inputs)
            const invocationInput = invocation.state.vmState ?? invocation.hogFunction.bytecode
            const eventId = invocation?.state.globals?.event?.uuid || 'Unknown event'

            try {
                let hogLogs = 0

                const asyncFunctionsNames = options.asyncFunctionsNames ?? ['fetch', 'sendEmail']
                const asyncFunctions = asyncFunctionsNames.reduce(
                    (acc, fn) => {
                        acc[fn] = async () => Promise.resolve()
                        return acc
                    },
                    {} as Record<string, (args: any[]) => Promise<void>>
                )

                const execHogOutcome = await execHog(invocationInput, {
                    globals,
                    timeout: this.hub.CDP_WATCHER_HOG_COST_TIMING_UPPER_MS,
                    maxAsyncSteps: MAX_ASYNC_STEPS, // NOTE: This will likely be configurable in the future
                    asyncFunctions: asyncFunctions,
                    functions: {
                        print: (...args) => {
                            hogLogs++
                            if (hogLogs === MAX_HOG_LOGS) {
                                addLog(
                                    'warn',
                                    `Function exceeded maximum log entries. No more logs will be collected. Event: ${eventId}`
                                )
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
                        generateMessagingPreferencesUrl: (identifier): string | null => {
                            return identifier && typeof identifier === 'string'
                                ? this.recipientTokensService.generatePreferencesUrl({
                                      team_id: invocation.teamId,
                                      identifier,
                                  })
                                : null
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
                                    addLog(
                                        'warn',
                                        `postHogCapture was called from an event that already executed this function. To prevent infinite loops, the event was not captured.`
                                    )
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
                        ...options.functions,
                    },
                })

                hogExecutionDuration.observe(execHogOutcome.durationMs)

                result.invocation.state.timings.push({
                    kind: 'hog',
                    duration_ms: execHogOutcome.durationMs,
                })

                if (!execHogOutcome.execResult || execHogOutcome.error || execHogOutcome.execResult.error) {
                    throw execHogOutcome.error ?? execHogOutcome.execResult?.error ?? new Error('Unknown error')
                }

                execRes = execHogOutcome.execResult

                // Store the result if execution finished
                if (execRes.finished && Boolean(execRes.result)) {
                    result.execResult = convertHogToJS(execRes.result)
                }
            } catch (e) {
                addLog('error', `Error executing function on event ${eventId}: ${e}`)
                throw e
            }

            result.finished = execRes.finished
            result.invocation.state.vmState = execRes.state

            if (!execRes.finished) {
                const args = (execRes.asyncFunctionArgs ?? []).map((arg) => convertHogToJS(arg))
                if (!execRes.state) {
                    // NOTE: This shouldn't be possible so is more of a type sanity check
                    throw new Error('State should be provided for async function')
                }

                if (execRes.asyncFunctionName) {
                    switch (execRes.asyncFunctionName) {
                        case 'fetch': {
                            // Sanitize the args
                            const [url, fetchOptions] = args as [string | undefined, Record<string, any> | undefined]

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

                            const fetchQueueParameters = CyclotronInvocationQueueParametersFetchSchema.parse({
                                type: 'fetch',
                                url,
                                method,
                                body,
                                headers: pickBy(headers, (v) => typeof v == 'string'),
                                ...(fetchOptions?.timeoutMs ? { timeoutMs: fetchOptions.timeoutMs } : {}),
                            })

                            result.invocation.queueParameters = fetchQueueParameters
                            break
                        }

                        case 'sendEmail': {
                            result.invocation.queueParameters = CyclotronInvocationQueueParametersEmailSchema.parse({
                                ...args[0],
                                type: 'email',
                            })
                            break
                        }
                        default:
                            throw new Error(`Unknown async function '${execRes.asyncFunctionName}'`)
                    }
                } else {
                    addLog('warn', `Function was not finished but also had no async function to execute.`)
                }
            } else {
                const totalDuration = result.invocation.state.timings.reduce(
                    (acc, timing) => acc + timing.duration_ms,
                    0
                )
                const messages = [`Function completed in ${formatNumber(totalDuration)}ms.`]
                if (execRes.state) {
                    messages.push(`Sync: ${formatNumber(execRes.state.syncDuration)}ms.`)
                    messages.push(`Mem: ${formatNumber(execRes.state.maxMemUsed / 1024)}kb.`)
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
                addLog('debug', messages.join(' '))
            }
        } catch (err) {
            result.error = err.message
            result.finished = true // Explicitly set to true to prevent infinite loops
        }

        return result
    }

    @instrumented('hog-executor.executeFetch')
    async executeFetch(
        invocation: CyclotronJobInvocationHogFunction
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        const templateId = invocation.hogFunction.template_id ?? 'unknown'
        if (invocation.queueParameters?.type !== 'fetch') {
            throw new Error('Bad invocation')
        }

        const params = invocation.queueParameters

        const result = createInvocationResult<CyclotronJobInvocationHogFunction>(
            invocation,
            {},
            {
                finished: false,
            }
        )
        const addLog = createAddLogFunction(result.logs)

        const method = params.method.toUpperCase()
        let headers = params.headers ?? {}

        if (params.url.startsWith('https://googleads.googleapis.com/') && !headers['developer-token']) {
            headers['developer-token'] = this.hub.CDP_GOOGLE_ADWORDS_DEVELOPER_TOKEN
        }

        const integrationInputs = await this.hogInputsService.loadIntegrationInputs(invocation.hogFunction)

        if (Object.keys(integrationInputs).length > 0) {
            for (const [key, value] of Object.entries(integrationInputs)) {
                const accessToken: string = value.value?.access_token_raw
                if (!accessToken) {
                    continue
                }

                const placeholder: string = ACCESS_TOKEN_PLACEHOLDER + invocation.hogFunction.inputs?.[key]?.value

                if (placeholder && accessToken) {
                    const replace = (val: string) => val.replaceAll(placeholder, accessToken)

                    params.body = params.body ? replace(params.body) : params.body
                    headers = Object.fromEntries(
                        Object.entries(params.headers ?? {}).map(([key, value]) => [
                            key,
                            typeof value === 'string' ? replace(value) : value,
                        ])
                    )
                    params.url = replace(params.url)
                }
            }
        }

        const fetchParams: FetchOptions = { method, headers }

        if (!['GET', 'HEAD'].includes(method) && params.body) {
            fetchParams.body = params.body
        }

        if (params.timeoutMs) {
            fetchParams.timeoutMs = params.timeoutMs
        }

        const { fetchError, fetchResponse, fetchDuration } = await cdpTrackedFetch({
            url: params.url,
            fetchParams,
            templateId,
        })

        result.invocation.state.timings.push({
            kind: 'async_function',
            duration_ms: fetchDuration,
        })

        result.invocation.state.attempts++

        if (!fetchResponse || (fetchResponse?.status && fetchResponse.status >= 400)) {
            const backoffMs = Math.min(
                this.hub.CDP_FETCH_BACKOFF_BASE_MS * result.invocation.state.attempts +
                    Math.floor(Math.random() * this.hub.CDP_FETCH_BACKOFF_BASE_MS),
                this.hub.CDP_FETCH_BACKOFF_MAX_MS
            )

            const canRetry = isFetchResponseRetriable(fetchResponse, fetchError)

            let message = `HTTP fetch failed on attempt ${result.invocation.state.attempts} with status code ${
                fetchResponse?.status ?? '(none)'
            }.`

            if (fetchError) {
                message += ` Error: ${fetchError.message}.`
            }

            if (canRetry) {
                message += ` Retrying in ${backoffMs}ms.`
            }

            addLog('error', message)

            if (canRetry && result.invocation.state.attempts < this.hub.CDP_FETCH_RETRIES) {
                await fetchResponse?.dump()
                result.invocation.queue = 'hog'
                // Filter out undefined timeoutMs to avoid snapshot issues
                const { timeoutMs, ...restParams } = params
                result.invocation.queueParameters = {
                    ...restParams,
                    ...(timeoutMs !== undefined ? { timeoutMs } : {}),
                }
                result.invocation.queuePriority = invocation.queuePriority + 1
                result.invocation.queueScheduledAt = DateTime.utc().plus({ milliseconds: backoffMs })

                return result
            } else {
                result.error = new Error(message)
            }
        }

        // Reset the attempts as we are done
        result.invocation.state.attempts = 0

        let body: unknown = undefined
        try {
            body = await fetchResponse?.text()

            if (typeof body === 'string') {
                try {
                    body = parseJSON(body)
                } catch (e) {
                    // Pass through the error
                }
            }
        } catch (e) {
            addLog('error', `Failed to parse response body: ${e.message}`)
            body = undefined
        }

        // Handle FCM push notification responses
        await this.handleFcmResponse(params.url, params.body, fetchResponse?.status, body, invocation.teamId, addLog)

        const hogVmResponse: {
            status: number
            body: unknown
        } = {
            status: fetchResponse?.status ?? 500,
            body,
        }

        // Finally we create the response object as the VM expects
        result.invocation.state.vmState!.stack.push(hogVmResponse)
        result.execResult = hogVmResponse

        result.metrics.push({
            team_id: invocation.teamId,
            app_source_id: invocation.functionId,
            metric_kind: 'other',
            metric_name: 'fetch',
            count: 1,
        })

        return result
    }

    private async handleFcmResponse(
        url: string,
        requestBody: string | null | undefined,
        status: number | undefined,
        responseBody: unknown,
        teamId: number,
        addLog: (level: 'debug' | 'warn' | 'error' | 'info', ...args: any[]) => void
    ): Promise<void> {
        // Check if this is an FCM API call
        if (!url.includes('fcm.googleapis.com/v1/projects/') || !url.includes('/messages:send')) {
            return
        }

        // TODOdin: Don't we have a way to pass in the token?
        let fcmToken: string | null = null

        try {
            if (requestBody && typeof requestBody === 'string') {
                const parsedBody = parseJSON(requestBody) as any
                fcmToken = parsedBody?.message?.token || null
            }
        } catch (e) {
            // Failed to parse request body, skip FCM handling
            return
        }

        if (!fcmToken) {
            return
        }
        // Handle success (200-299)
        if (status && status >= 200 && status < 300) {
            if (fcmToken) {
                try {
                    await this.pushSubscriptionsManager.updateLastSuccessfullyUsedAtByToken(teamId, fcmToken)
                    addLog('debug', `Updated last_successfully_used_at for FCM token`)
                } catch (error) {
                    addLog('warn', `Failed to update last_successfully_used_at for FCM token: ${error}`)
                }
            }
            // FCM is used for Android push notifications
            pushNotificationSentCounter.labels({ platform: 'android' }).inc()
            return
        }

        // Handle 404 - unregistered token
        if (status === 404) {
            try {
                await this.pushSubscriptionsManager.deactivateToken(teamId, fcmToken, 'unregistered token')
                addLog('info', `Deactivated push subscription token due to 404 (unregistered token)`)
            } catch (error) {
                addLog('warn', `Failed to deactivate push subscription token: ${error}`)
            }
            return
        }

        // Handle 400 with INVALID_ARGUMENT error
        if (status === 400) {
            try {
                let shouldDeactivate = false
                if (responseBody && typeof responseBody === 'object') {
                    const errorBody = responseBody as any
                    const error = errorBody?.error
                    if (error?.code === 400) {
                        // Check for INVALID_ARGUMENT in details
                        const details = error?.details || []
                        for (const detail of details) {
                            if (
                                detail['@type'] === 'type.googleapis.com/google.firebase.fcm.v1.FcmError' &&
                                detail.errorCode === 'INVALID_ARGUMENT'
                            ) {
                                shouldDeactivate = true
                                break
                            }
                        }
                    }
                }

                if (shouldDeactivate) {
                    await this.pushSubscriptionsManager.deactivateToken(teamId, fcmToken, 'invalid token')
                    addLog('info', `Deactivated push subscription token due to 400 INVALID_ARGUMENT (invalid token)`)
                }
            } catch (error) {
                addLog('warn', `Failed to deactivate push subscription token: ${error}`)
            }
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

        // We don't want to add "REDACTED" for empty strings
        return values.filter((v) => v.trim())
    }
}
