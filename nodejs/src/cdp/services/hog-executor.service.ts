import { DateTime } from 'luxon'
import { Histogram } from 'prom-client'

import { ExecResult, convertHogToJS } from '@posthog/hogvm'

import { instrumented } from '~/common/tracing/tracing-utils'
import { logger } from '~/common/utils/logger'

import type {
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionInvocationGlobals,
    HogFunctionInvocationGlobalsWithInputs,
    HogFunctionType,
} from '../types'
import { createAddLogFunction, getSensitiveValues, redactSensitiveValues, sanitizeLogMessage } from '../utils'
import { execHog } from '../utils/hog-exec'
import { convertToHogFunctionFilterGlobal, filterFunctionInstrumented } from '../utils/hog-function-filtering'
import { createInvocationResult } from '../utils/invocation-utils'
import { HogInputsService } from './hog-inputs.service'

export interface HogExecutorConfig {
    /** Hard wall-clock limit for one Hog program. The VM aborts the invocation once it elapses. */
    executionTimeoutMs: number
}

export const MAX_ASYNC_STEPS = 5
export const MAX_HOG_LOGS = 25

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

function formatNumber(val: number) {
    return Number(val.toPrecision(2)).toString()
}

/**
 * Called when the VM suspends on an async function instead of finishing. The Hog core has no way
 * to service one, so a caller that wants async functions (fetch, email, push) must supply this -
 * see HogExecutorAsyncService. Without it a suspending function is an error.
 */
export type HogExecutorAsyncFunctionHandler = (
    call: { name: string; args: any[]; globals: HogFunctionInvocationGlobalsWithInputs },
    result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>
) => Promise<void>

/** The parts of an earlier step's result that carry forward into the next one. */
export type HogExecutorPreviousResult = Pick<
    Partial<CyclotronJobInvocationResult>,
    'finished' | 'capturedPostHogEvents' | 'warehouseWebhookPayloads' | 'logs' | 'metrics' | 'error' | 'execResult'
>

export type HogExecutorExecuteOptions = {
    functions?: Record<string, (args: unknown[]) => unknown>
    /**
     * Async functions are stubbed in the VM so the program can call them and suspend. Defaults to
     * none, meaning any async call is unknown to the VM - callers that can service them pass their
     * names (and an `onAsyncFunction` handler) in.
     */
    asyncFunctionsNames?: string[]
    onAsyncFunction?: HogExecutorAsyncFunctionHandler
}

/**
 * Synchronous Hog execution: build inputs, run the bytecode, collect logs, metrics and timings.
 *
 * Deliberately has no fetch, email, push, team or Redis dependency - transformations run in
 * ingestion on exactly this and must not inherit CDP delivery infrastructure. Anything that needs
 * to suspend and resume belongs in HogExecutorAsyncService, which wraps this one.
 */
export class HogExecutorService {
    constructor(
        private config: HogExecutorConfig,
        private hogInputsService: HogInputsService
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

    @instrumented({ key: 'hog-executor.execute', sendException: false })
    async execute(
        invocation: CyclotronJobInvocationHogFunction,
        options: HogExecutorExecuteOptions = {},
        previousResult: HogExecutorPreviousResult = {}
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

        // Declared out here so the terminal catch can mask secrets out of `result.error`, which is
        // persisted to `hog_invocation_results.error_message` and rendered in the Invocations tab.
        let sensitiveValues: string[] = []

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

            sensitiveValues = this.getSensitiveValues(invocation.hogFunction, globals.inputs)
            const invocationInput = invocation.state.vmState ?? invocation.hogFunction.bytecode
            const eventId = invocation?.state.globals?.event?.uuid || 'Unknown event'

            try {
                let hogLogs = 0

                const asyncFunctions = (options.asyncFunctionsNames ?? []).reduce(
                    (acc, fn) => {
                        acc[fn] = async () => Promise.resolve()
                        return acc
                    },
                    {} as Record<string, (args: any[]) => Promise<void>>
                )

                const execHogOutcome = await execHog(invocationInput, {
                    globals,
                    timeout: this.config.executionTimeoutMs,
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
                addLog(
                    'error',
                    sanitizeLogMessage([`Error executing function on event ${eventId}: ${e}`], sensitiveValues)
                )
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
                    if (!options.onAsyncFunction) {
                        throw new Error(
                            `Function suspended on async function '${execRes.asyncFunctionName}' but this executor cannot run async functions`
                        )
                    }
                    await options.onAsyncFunction({ name: execRes.asyncFunctionName, args, globals }, result)
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
            result.error = redactSensitiveValues(err.message, sensitiveValues)
            result.finished = true // Explicitly set to true to prevent infinite loops
        }

        return result
    }

    getSensitiveValues(hogFunction: HogFunctionType, inputs: Record<string, any>): string[] {
        return getSensitiveValues(hogFunction, inputs)
    }
}
