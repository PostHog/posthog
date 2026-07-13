import { DateTime } from 'luxon'
import { Counter, Histogram } from 'prom-client'

import { ExecResult, convertHogToJS } from '@posthog/hogvm'

import { ACCESS_TOKEN_PLACEHOLDER } from '~/common/config/constants'
import { instrumented } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { FetchOptions, FetchResponse, InvalidRequestError, SecureRequestError, fetch } from '~/common/utils/request'
import { TeamManager } from '~/common/utils/team-manager'
import { tryCatch } from '~/common/utils/try-catch'
import { UUIDT } from '~/common/utils/utils'

import { PluginsServerConfig } from '../../types'
import { getAsyncFunctionHandler, getRegisteredAsyncFunctionNames } from '../async-function-registry'
import '../async-functions'
import type {
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
import { createAddLogFunction, destinationE2eLagMsSummary, sanitizeLogMessage } from '../utils'
import { resolveAwsSigV4Credentials, signAwsRequest } from '../utils/aws-sigv4'
import { execHog } from '../utils/hog-exec'
import { convertToHogFunctionFilterGlobal, filterFunctionInstrumented } from '../utils/hog-function-filtering'
import { createInvocation, createInvocationResult } from '../utils/invocation-utils'
import { isNonFailureStatus } from '../utils/non-failure-status-codes'
import { HogInputsService } from './hog-inputs.service'
import { EmailService } from './messaging/email.service'
import { RecipientTokensService } from './messaging/recipient-tokens.service'
import {
    SELF_LOOP_MAX_DEPTH,
    getSelfLoopDepth,
    injectSelfLoopDepth,
    isPostHogIngestUrl,
    isSelfReferentialIngestFetch,
    selfLoopGuardCounter,
} from './self-loop-guard'

/** Narrowed config type for CDP fetch retry settings, used by native/segment destination executors */
export type CdpFetchConfig = Pick<
    PluginsServerConfig,
    'CDP_FETCH_RETRIES' | 'CDP_FETCH_BACKOFF_BASE_MS' | 'CDP_FETCH_BACKOFF_MAX_MS'
>

export interface HogExecutorConfig {
    hogCostTimingUpperMs: number
    googleAdwordsDeveloperToken: string
    fetchRetries: number
    fetchBackoffBaseMs: number
    fetchBackoffMaxMs: number
}

export interface HogExecutorAsyncContext {
    teamManager: TeamManager
    siteUrl: string
}

const cdpEmailQueuedTotal = new Counter({
    name: 'cdp_email_queued_total',
    help: 'Total emails routed to the dedicated email queue',
})

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

const cdpHttpRequestTimingRetried = new Histogram({
    name: 'cdp_http_request_timing_retried_ms',
    help: 'Timing of HTTP requests that required immediate retry after a connection-level error',
    buckets: [0, 10, 20, 50, 100, 200, 500, 1000, 2000, 3000, 5000, 10000],
})

// Stale keep-alive connections produce these errors when the server has closed its end before
// we reuse the socket. A single in-process retry on a fresh connection may resolve them immediately.
export function isConnectionLevelError(error: any): boolean {
    return (
        error?.code === 'UND_ERR_SOCKET' || // undici SocketError ("other side closed")
        error?.code === 'ECONNRESET' ||
        error?.code === 'EPIPE' ||
        error?.message === 'other side closed' ||
        error?.message === 'socket hang up'
    )
}

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

    let [fetchError, fetchResponse] = await tryCatch(async () => await fetch(url, fetchParams))

    const fetchDuration = performance.now() - start
    cdpHttpRequestTiming.observe(fetchDuration)
    cdpHttpRequests.inc({ status: fetchResponse?.status?.toString() ?? 'error', template_id: templateId })

    if (fetchError && isConnectionLevelError(fetchError)) {
        logger.warn('🦔', '[cdpTrackedFetch] Connection-level error detected, immediately retrying fetch once', {
            url,
            error: fetchError,
        })
        ;[fetchError, fetchResponse] = await tryCatch(async () => await fetch(url, fetchParams))
        const retryDuration = performance.now() - start
        cdpHttpRequestTimingRetried.observe(retryDuration)
        cdpHttpRequests.inc({ status: fetchResponse?.status?.toString() ?? 'error', template_id: templateId })
        return { fetchError, fetchResponse, fetchDuration: retryDuration }
    }

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
    asyncFunctionsNames?: string[]
}

export type HogExecutorExecuteAsyncOptions = HogExecutorExecuteOptions & {
    maxAsyncFunctions?: number
    maxFetchRetries?: number
    // When true, emails are sent inline via EmailService instead of being routed to
    // the dedicated email queue. Used by the test panel — the test endpoint executes
    // in-process and never enqueues to cyclotron, so routing would leave the job
    // unworked.
    sendEmailsInline?: boolean
}

export class HogExecutorService {
    constructor(
        private config: HogExecutorConfig,
        private asyncContext: HogExecutorAsyncContext,
        private hogInputsService: HogInputsService,
        private emailService: EmailService,
        private recipientTokensService: RecipientTokensService
    ) {}

    async buildInputsWithGlobals(
        hogFunction: HogFunctionType,
        globals: HogFunctionInvocationGlobals,
        additionalInputs?: Record<string, any>
    ): Promise<HogFunctionInvocationGlobalsWithInputs> {
        return this.hogInputsService.buildInputsWithGlobals(hogFunction, globals, additionalInputs)
    }

    /**
     * For mapping destinations the per-mapping inputs (e.g. the Google Ads
     * `gclid`) are resolved only for mappings whose filters match the event —
     * see `buildHogFunctionInvocations`, which merges `mapping.inputs` when it
     * first builds the invocation. The rerun path re-enqueues invocations with
     * `inputs` stripped and keeps no record of which mapping produced them, so
     * a plain rebuild against the top-level config drops those inputs entirely
     * and any function guarding on them (e.g. `if (empty(inputs.gclid))`)
     * early-exits. Re-match the mappings here against the (current) config to
     * rebuild the additional inputs before the executor resolves them.
     *
     * When several mappings match one event the original produced a separate
     * invocation per mapping; the stored row can't be tied back to a single
     * one, so we merge all matching mappings' inputs — exact for the common
     * single-mapping case and strictly better than dropping them.
     */
    private async resolveMappingInputs(
        hogFunction: HogFunctionType,
        globals: HogFunctionInvocationGlobals
    ): Promise<HogFunctionType['inputs'] | undefined> {
        const mappings = hogFunction.mappings
        if (!mappings || mappings.length === 0) {
            return undefined
        }

        const filterGlobals = convertToHogFunctionFilterGlobal(globals)
        let merged: HogFunctionType['inputs'] | undefined

        for (const mapping of mappings) {
            if (!mapping.inputs) {
                continue
            }
            const { match } = await filterFunctionInstrumented({
                fn: hogFunction,
                filters: mapping.filters,
                filterGlobals,
            })
            if (match) {
                merged = { ...(merged ?? {}), ...mapping.inputs }
            }
        }

        return merged
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
                        url: `${triggerGlobals.project.url}/functions/${hogFunction.id}/configuration/`,
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

                await Promise.all(
                    hogFunction.mappings.map(async (mapping) => {
                        if (!(await _filterHogFunction(hogFunction, mapping.filters, filterGlobals))) {
                            return
                        }

                        const invocation = await _buildInvocation(hogFunction, mapping.inputs ?? {})
                        if (!invocation) {
                            return
                        }

                        invocations.push(invocation)
                    })
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

                // Queue-aware routing: each worker can execute some actions inline
                // and routes others to a specialized queue. The email worker sends
                // emails inline but routes fetches back to hogflow. The hogflow
                // worker does fetches inline but routes emails to the email queue.
                //
                // Future: once we add an execution time budget, the email worker
                // will also handle fetches inline. The only reason to reschedule
                // back to hogflow will be when overall execution time exceeds the
                // budget, to avoid blocking the queue.
                if (queueParamsType === 'fetch') {
                    if (invocation.queue === 'email') {
                        result = this.routeToQueue(
                            nextInvocation,
                            nextInvocation.queueMetadata?.originQueue ?? 'hogflow'
                        )
                    } else {
                        result = await this.executeFetch(nextInvocation, options)
                    }
                } else if (queueParamsType === 'email') {
                    // Route to the email queue only if we're not already there and the
                    // caller hasn't asked for inline-only execution (e.g. the test panel).
                    const routeToEmailQueue = invocation.queue !== 'email' && !options?.sendEmailsInline
                    if (routeToEmailQueue) {
                        result = this.routeEmailToQueue(nextInvocation)
                    } else {
                        // `sendEmailsInline` is only set by the test panel, so it doubles as the
                        // "this is a test send" signal — propagated into the email's tracking code.
                        result = await this.emailService.executeSendEmail(
                            nextInvocation,
                            options?.sendEmailsInline ?? false
                        )
                    }
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

            // If we have finished _or_ something has been scheduled to run later _or_ the job was routed to a different queue then we break the loop
            if (result.finished || result.invocation.queueScheduledAt || result.invocation.queue !== invocation.queue) {
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

    /**
     * Routes an email send to the dedicated email queue instead of sending inline.
     * The email worker will pick this up, send via SES, and return the job to the
     * original queue so the workflow can continue.
     */
    private routeEmailToQueue(
        invocation: CyclotronJobInvocationHogFunction
    ): CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> {
        const result = createInvocationResult<CyclotronJobInvocationHogFunction>(
            invocation,
            {
                queue: 'email',
                queueParameters: invocation.queueParameters,
                queueMetadata: {
                    ...invocation.queueMetadata,
                    originQueue: invocation.queue,
                },
            },
            { finished: false }
        )

        result.metrics.push({
            team_id: invocation.teamId,
            app_source_id: invocation.parentRunId ?? invocation.functionId,
            instance_id: invocation.state.actionId || invocation.id,
            metric_kind: 'email',
            metric_name: 'email_queued',
            count: 1,
        })

        cdpEmailQueuedTotal.inc()

        return result
    }

    private routeToQueue(
        invocation: CyclotronJobInvocationHogFunction,
        targetQueue: string
    ): CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> {
        return createInvocationResult<CyclotronJobInvocationHogFunction>(
            invocation,
            {
                queue: targetQueue as CyclotronJobInvocationHogFunction['queue'],
                queueParameters: invocation.queueParameters,
                queueMetadata: undefined,
            },
            { finished: false }
        )
    }

    @instrumented({ key: 'hog-executor.execute', sendException: false })
    async execute(
        invocation: CyclotronJobInvocationHogFunction,
        options: HogExecutorExecuteOptions = {},
        previousResult: Pick<
            Partial<CyclotronJobInvocationResult>,
            | 'finished'
            | 'capturedPostHogEvents'
            | 'warehouseWebhookPayloads'
            | 'logs'
            | 'metrics'
            | 'error'
            | 'execResult'
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
                // Build inputs here when the invocation arrives without them.
                // This is a supported path, not a transitional fallback: the
                // rerun pipeline deliberately re-enqueues invocations with only
                // the bare globals so the run resolves inputs against the
                // current hog function config. Callers that pre-resolve inputs
                // (e.g. the mappings path) skip the rebuild.
                if (invocation.state.globals.inputs) {
                    globals = invocation.state.globals
                } else {
                    // Mapping destinations need their per-mapping inputs
                    // re-merged here — they aren't part of the top-level config
                    // and were stripped from the rerun blob.
                    const additionalInputs = await this.resolveMappingInputs(
                        invocation.hogFunction,
                        invocation.state.globals
                    )
                    globals = await this.hogInputsService.buildInputsWithGlobals(
                        invocation.hogFunction,
                        invocation.state.globals,
                        additionalInputs
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

                const asyncFunctionsNames = options.asyncFunctionsNames ?? getRegisteredAsyncFunctionNames()
                const asyncFunctions = asyncFunctionsNames.reduce(
                    (acc, fn) => {
                        acc[fn] = async () => Promise.resolve()
                        return acc
                    },
                    {} as Record<string, (args: any[]) => Promise<void>>
                )

                const execHogOutcome = await execHog(invocationInput, {
                    globals,
                    timeout: this.config.hogCostTimingUpperMs,
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
                            const distinctId = event.distinct_id || globals.event?.distinct_id || globals.person?.id
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

                                if (executionCount > 9) {
                                    addLog(
                                        'warn',
                                        `postHogCapture was called from an event that already executed this function 10 times previously. To prevent unbounded infinite loops, the event was not captured.`
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
                    const handler = getAsyncFunctionHandler(execRes.asyncFunctionName)
                    if (!handler) {
                        throw new Error(`Unknown async function '${execRes.asyncFunctionName}'`)
                    }
                    // Async handlers are responsible for ensuring the resumed VM stack contains
                    // their return value before it next runs - either by pushing directly onto
                    // result.invocation.state.vmState.stack (synchronous handlers) or by deferring
                    // the push to executeFetch / executeSendEmail (queueing handlers). See the
                    // RETURN-VALUE CONTRACT comment in cdp/async-functions/example.ts.
                    await handler.execute(
                        args,
                        { invocation: result.invocation, globals, ...this.asyncContext },
                        result
                    )
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
        invocation: CyclotronJobInvocationHogFunction,
        options?: Pick<HogExecutorExecuteAsyncOptions, 'maxFetchRetries'>
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
            headers['developer-token'] = this.config.googleAdwordsDeveloperToken
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
                        Object.entries(params.headers ?? {}).map(([key, value]) => [key, replace(value)])
                    )
                    params.url = replace(params.url)
                }
            }
        }

        // Bound event-forwarding loops: a fetch back into this project's own ingestion
        // endpoint re-enters the pipeline and can re-trigger this same function. The
        // ingest-URL check gates the team lookup so external fetches (the common case) pay
        // nothing, and the whole block fails open - the guard must never break a destination
        // it was only meant to protect.
        if (isPostHogIngestUrl(params.url)) {
            try {
                const team = await this.asyncContext.teamManager.getTeam(invocation.teamId)
                if (team && isSelfReferentialIngestFetch({ url: params.url, body: params.body, team })) {
                    // Depth is counted per function id, so this destination is bounded only
                    // by how many times IT has re-fed itself - an event that merely passed
                    // through other functions can never trip the guard for it.
                    const functionId = invocation.hogFunction.id
                    const depth = getSelfLoopDepth(invocation.state.globals.event?.properties, functionId)

                    if (depth >= SELF_LOOP_MAX_DEPTH) {
                        // This destination has re-fed itself to the cap - break it.
                        selfLoopGuardCounter.inc({ mode: 'enforce', action: 'blocked' })
                        addLog(
                            'error',
                            `Refusing to fetch a PostHog ingestion endpoint using this project's own API key - this destination's event-forwarding loop has already repeated ${SELF_LOOP_MAX_DEPTH} times. To capture an event back into this project use the 'postHogCapture' helper, or to enrich incoming events use a transformation.`
                        )
                        result.error = new Error('Self-referential event-forwarding loop blocked at max depth')
                        result.finished = true
                        return result
                    }
                    // Under the cap - stamp this destination's next hop and proceed.
                    selfLoopGuardCounter.inc({ mode: 'enforce', action: 'allowed_with_counter' })
                    params.body = injectSelfLoopDepth(params.body, functionId, depth + 1)
                }
            } catch (err) {
                logger.warn('🦔', '[HogExecutor] Self-loop guard skipped due to an internal error', {
                    error: err,
                    teamId: invocation.teamId,
                })
            }
        }

        // AWS SigV4 signatures expire after ~5 minutes. Sign immediately before the
        // fetch (every attempt — including retries) so a request that sat in the
        // backoff queue or whose first attempt timed out cannot reach AWS with a
        // stale signature. Signing artifacts (Authorization, X-Amz-Date) are
        // regenerated here and never persisted back to queueParameters. Credential
        // resolution + missing-input handling live in `aws-sigv4.ts` — see
        // `resolveAwsSigV4Credentials` for the encrypted_inputs/inputs lookup order.
        let signedHeaders = headers
        if (params.aws_sigv4) {
            const resolved = resolveAwsSigV4Credentials(params.aws_sigv4, invocation.hogFunction)
            if (!resolved.ok) {
                addLog('error', resolved.error)
                result.error = new Error(resolved.error)
                result.finished = true
                return result
            }
            signedHeaders = signAwsRequest({
                method,
                url: params.url,
                body: params.body ?? '',
                headers,
                credentials: resolved.credentials,
            })
        }

        const fetchParams: FetchOptions = { method, headers: signedHeaders }

        if (!['GET', 'HEAD'].includes(method) && params.body) {
            fetchParams.body = params.body
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
            const nonFailureSchemaEntry = invocation.hogFunction.inputs_schema?.find(
                (s) => s.type === 'non_failure_status_codes'
            )
            const nonFailureConfig = nonFailureSchemaEntry
                ? (invocation.hogFunction.inputs?.[nonFailureSchemaEntry.key]?.value as
                      | Array<number | string>
                      | null
                      | undefined)
                : undefined
            const isNonFailure = isNonFailureStatus(fetchResponse?.status, nonFailureConfig)

            const backoffMs = Math.min(
                this.config.fetchBackoffBaseMs * result.invocation.state.attempts +
                    Math.floor(Math.random() * this.config.fetchBackoffBaseMs),
                this.config.fetchBackoffMaxMs
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

            addLog(isNonFailure ? 'info' : 'error', message)

            const maxRetries = options?.maxFetchRetries ?? this.config.fetchRetries
            if (canRetry && result.invocation.state.attempts < maxRetries) {
                await fetchResponse?.dump()
                result.invocation.queueParameters = params
                result.invocation.queuePriority = invocation.queuePriority + 1
                result.invocation.queueScheduledAt = DateTime.utc().plus({ milliseconds: backoffMs })

                return result
            } else if (!isNonFailure) {
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
                } catch {
                    // Pass through the error
                }
            }
        } catch (e) {
            addLog('error', `Failed to parse response body: ${e.message}`)
            body = undefined
        }

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
            app_source_id: invocation.parentRunId ?? invocation.functionId,
            metric_kind: 'other',
            metric_name: 'fetch',
            count: 1,
        })

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
