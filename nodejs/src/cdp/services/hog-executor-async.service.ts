import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { ACCESS_TOKEN_PLACEHOLDER } from '~/common/config/constants'
import { instrumented } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { FetchOptions } from '~/common/utils/request'
import { TeamManager } from '~/common/utils/team-manager'

import { getAsyncFunctionHandler, getRegisteredAsyncFunctionNames } from '../async-function-registry'
import '../async-functions'
import type {
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    MinimalAppMetric,
    MinimalLogEntry,
} from '../types'
import { createAddLogFunction, destinationE2eLagMsSummary } from '../utils'
import { resolveAwsSigV4Credentials, signAwsRequest } from '../utils/aws-sigv4'
import { cdpTrackedFetch, fetchErrorDetail, isFetchResponseRetriable } from '../utils/cdp-fetch'
import { createInvocationResult } from '../utils/invocation-utils'
import { isNonFailureStatus } from '../utils/non-failure-status-codes'
import { ScopedServiceJwt } from '../utils/scoped-service-jwt'
import { HogExecutorExecuteOptions, HogExecutorPreviousResult, HogExecutorService } from './hog-executor.service'
import { HogInputsService } from './hog-inputs.service'
import { EMAIL_QUEUE_PRIORITY, getEmailQueuePriorityClass } from './messaging/email-priority'
import { EmailService } from './messaging/email.service'
import { PushNotificationService } from './messaging/push-notification.service'
import { RecipientTokensService } from './messaging/recipient-tokens.service'
import {
    SELF_LOOP_MAX_DEPTH,
    getSelfLoopDepth,
    injectSelfLoopDepth,
    isPostHogIngestUrl,
    isSelfReferentialIngestFetch,
    selfLoopGuardCounter,
} from './self-loop-guard'

const cdpEmailQueuedTotal = new Counter({
    name: 'cdp_email_queued_total',
    help: 'Total emails routed to the dedicated email queue',
    labelNames: ['priority_class'] as const,
})

export interface HogExecutorAsyncConfig {
    googleAdwordsDeveloperToken: string
    fetchRetries: number
    fetchBackoffBaseMs: number
    fetchBackoffMaxMs: number
    siteUrl: string
    internalApiBaseUrl: string
}

/**
 * Every capability the async functions can reach is required - an async executor missing one is a
 * misconfiguration, not a supported mode, and would only surface as a runtime throw deep inside a
 * customer's function. Callers that don't need any of them want HogExecutorService directly.
 */
export interface HogExecutorAsyncDependencies {
    teamManager: TeamManager
    conversationsTicketsJwt: ScopedServiceJwt
    hogInputsService: HogInputsService
    emailService: EmailService
    recipientTokensService: RecipientTokensService
    pushNotificationService: PushNotificationService
}

export type HogExecutorExecuteAsyncOptions = HogExecutorExecuteOptions & {
    maxAsyncFunctions?: number
    maxFetchRetries?: number
    // Set only by the editor's test panel ("Run test"), marking this invocation as a test send. Two
    // effects: emails run inline via EmailService instead of routing to the email queue (the test
    // endpoint executes in-process and never enqueues to cyclotron, so routing would leave the job
    // unworked), and messaging channels skip metrics/assets so a test doesn't pollute the workflow's
    // Metrics and Assets tabs.
    isTest?: boolean
}

/**
 * Hog execution plus everything a function needs to suspend and resume: fetches, emails, push
 * notifications, and the queue routing between the workers that service them.
 *
 * The synchronous Hog core is exposed as `hogExecutor` rather than re-wrapped, so callers reach
 * `buildInputsWithGlobals` / `buildHogFunctionInvocations` / `getSensitiveValues` on the thing that
 * actually owns them.
 */
export class HogExecutorAsyncService {
    constructor(
        public readonly hogExecutor: HogExecutorService,
        private config: HogExecutorAsyncConfig,
        private deps: HogExecutorAsyncDependencies
    ) {}

    @instrumented('hog-executor.executeWithAsyncFunctions')
    async executeWithAsyncFunctions(
        invocation: CyclotronJobInvocationHogFunction,
        options?: HogExecutorExecuteAsyncOptions
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        let asyncFunctionCount = 0
        const maxAsyncFunctions = options?.maxAsyncFunctions ?? 1

        // Shared with inline async handlers (see AsyncFunctionContext.consumeInlineAsyncBudget):
        // they do real network I/O without ever setting queueParameters, so the queued-type
        // counting below never sees them. Without this they could run unbounded up to the VM's
        // own step cap, each holding this worker slot for the full retry round instead of
        // rescheduling like a queued fetch does.
        const consumeInlineAsyncBudget = (): void => {
            asyncFunctionCount++
            if (asyncFunctionCount > maxAsyncFunctions) {
                throw new Error(
                    `Max async functions reached: ${maxAsyncFunctions}. This function performed too many API calls in a single execution.`
                )
            }
        }

        let result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> | null = null
        const metrics: MinimalAppMetric[] = []
        const logs: MinimalLogEntry[] = []

        while (!result || !result.finished) {
            const nextInvocation: CyclotronJobInvocationHogFunction = result?.invocation ?? invocation

            const queueParamsType = nextInvocation.queueParameters?.type
            if (['fetch', 'sendPushNotification', 'email'].includes(queueParamsType ?? '')) {
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
                        // Intermediate results clone away queueMetadata (createInvocationResult
                        // drops it unless the target queue is passed explicitly), so read the
                        // stash through the entry invocation too — it still carries the row's copy.
                        result = this.routeToQueue(
                            nextInvocation,
                            nextInvocation.queueMetadata?.originQueue ??
                                invocation.queueMetadata?.originQueue ??
                                'hogflow',
                            nextInvocation.queueMetadata?.originPriority ??
                                invocation.queueMetadata?.originPriority ??
                                invocation.queuePriority
                        )
                    } else {
                        result = await this.executeFetch(nextInvocation, options)
                    }
                } else if (queueParamsType === 'sendPushNotification') {
                    result = await this.deps.pushNotificationService.executeSendPushNotification(
                        nextInvocation,
                        options?.isTest ?? false
                    )
                } else if (queueParamsType === 'email') {
                    // Route to the email queue unless this is a test run: tests execute in-process and
                    // never enqueue, so routing would leave the job unworked.
                    const routeToEmailQueue = invocation.queue !== 'email' && !options?.isTest
                    if (routeToEmailQueue) {
                        // Stash the entry invocation's priority as the origin, not nextInvocation's:
                        // an earlier execute()/executeFetch() in this loop cloned the invocation and
                        // reset its queuePriority to 0, so reading nextInvocation here would restore 0
                        // on return and jump the run to the front of the origin queue.
                        result = this.routeEmailToQueue(nextInvocation, invocation.queuePriority)
                    } else {
                        // A flow already on the email queue sends inline, so this send never went
                        // through routeEmailToQueue's classification. Refresh the priority from
                        // the current action's metadata so a throttle retry re-queues under this
                        // send's class rather than the previous email action's.
                        if (invocation.queue === 'email') {
                            nextInvocation.queuePriority =
                                EMAIL_QUEUE_PRIORITY[getEmailQueuePriorityClass(nextInvocation.hogFunction.metadata)]
                        }
                        // isTest is forwarded so a test send stays out of the email's engagement tracking.
                        result = await this.deps.emailService.executeSendEmail(nextInvocation, options?.isTest ?? false)
                    }
                } else {
                    throw new Error(`Unknown queue type: ${queueParamsType}`)
                }
            } else {
                // Finish execution, carrying forward previous execResult
                // Tricky: We don't pass metrics in previousResult as they're accumulated in the local metrics array
                const { metrics: _m, logs: _l, ...previousResultWithoutMetrics } = result || {}
                result = await this.execute(
                    nextInvocation,
                    options,
                    previousResultWithoutMetrics,
                    consumeInlineAsyncBudget
                )
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
     * A single Hog step with async functions available: the program can call `fetch`, `sendEmail`
     * and friends, and its handler leaves the queue parameters the resumed run needs.
     */
    async execute(
        invocation: CyclotronJobInvocationHogFunction,
        options: HogExecutorExecuteOptions = {},
        previousResult: HogExecutorPreviousResult = {},
        // Callers outside executeWithAsyncFunctions' loop (e.g. the source-webhooks consumer)
        // run at most one async step per execute() call already, so a no-op budget is safe there.
        consumeInlineAsyncBudget: () => void = () => {}
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        return this.hogExecutor.execute(
            invocation,
            {
                ...options,
                asyncFunctionsNames: options.asyncFunctionsNames ?? getRegisteredAsyncFunctionNames(),
                functions: {
                    generateMessagingPreferencesUrl: (identifier): string | null => {
                        return identifier && typeof identifier === 'string'
                            ? this.deps.recipientTokensService.generatePreferencesUrl({
                                  team_id: invocation.teamId,
                                  identifier,
                              })
                            : null
                    },
                    ...options.functions,
                },
                onAsyncFunction: async ({ name, args, globals }, result) => {
                    const handler = getAsyncFunctionHandler(name)
                    if (!handler) {
                        throw new Error(`Unknown async function '${name}'`)
                    }
                    // Async handlers are responsible for ensuring the resumed VM stack contains
                    // their return value before it next runs - either by pushing directly onto
                    // result.invocation.state.vmState.stack (synchronous handlers) or by deferring
                    // the push to executeFetch / executeSendEmail (queueing handlers). See the
                    // RETURN-VALUE CONTRACT comment in cdp/async-functions/example.ts.
                    await handler.execute(
                        args,
                        {
                            invocation: result.invocation,
                            globals,
                            teamManager: this.deps.teamManager,
                            siteUrl: this.config.siteUrl,
                            internalApiBaseUrl: this.config.internalApiBaseUrl,
                            conversationsTicketsJwt: this.deps.conversationsTicketsJwt,
                            consumeInlineAsyncBudget,
                        },
                        result
                    )
                },
            },
            previousResult
        )
    }

    /**
     * Routes an email send to the dedicated email queue instead of sending inline.
     * The email worker will pick this up, send via SES, and return the job to the
     * original queue so the workflow can continue.
     */
    private routeEmailToQueue(
        invocation: CyclotronJobInvocationHogFunction,
        originPriority: number
    ): CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> {
        const priorityClass = getEmailQueuePriorityClass(invocation.hogFunction.metadata)
        const result = createInvocationResult<CyclotronJobInvocationHogFunction>(
            invocation,
            {
                queue: 'email',
                // The email queue dequeues transactional-class sends ahead of bulk ones;
                // originPriority is stashed so routeToQueue can restore the pre-email
                // priority when the job returns to its origin queue, keeping the email
                // classes out of the hogflow queue's ordering.
                queuePriority: EMAIL_QUEUE_PRIORITY[priorityClass],
                queueParameters: invocation.queueParameters,
                queueMetadata: {
                    ...invocation.queueMetadata,
                    originQueue: invocation.queue,
                    originPriority,
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

        cdpEmailQueuedTotal.labels(priorityClass).inc()

        return result
    }

    private routeToQueue(
        invocation: CyclotronJobInvocationHogFunction,
        targetQueue: string,
        originPriority: number
    ): CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction> {
        return createInvocationResult<CyclotronJobInvocationHogFunction>(
            invocation,
            {
                queue: targetQueue as CyclotronJobInvocationHogFunction['queue'],
                // Restore the priority the job had before routeEmailToQueue reclassified
                // it, so an email-class value never orders jobs on the origin queue.
                queuePriority: originPriority,
                queueParameters: invocation.queueParameters,
                queueMetadata: undefined,
            },
            { finished: false }
        )
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

        const integrationInputs = await this.deps.hogInputsService.loadIntegrationInputs(invocation.hogFunction)

        if (Object.keys(integrationInputs).length > 0) {
            for (const [key, value] of Object.entries(integrationInputs)) {
                const inputValue = value.value
                // integration_multi inputs resolve to an array of integrations (e.g. push channels)
                // and don't participate in the single access-token placeholder substitution below.
                if (Array.isArray(inputValue) || !inputValue) {
                    continue
                }
                const accessToken: string = inputValue.access_token_raw
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
                const team = await this.deps.teamManager.getTeam(invocation.teamId)
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
            teamId: invocation.teamId,
            hogFunctionId: invocation.hogFunction.id,
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
            const maxRetries = options?.maxFetchRetries ?? this.config.fetchRetries
            // `canRetry` only says the failure class is retriable. On the last attempt it is still
            // true while no retry follows, so the customer-facing log has to gate on the same
            // condition the scheduling below does.
            const willRetry = canRetry && result.invocation.state.attempts < maxRetries

            let message = `HTTP fetch failed on attempt ${result.invocation.state.attempts} with status code ${
                fetchResponse?.status ?? '(none)'
            }.`

            if (fetchError) {
                message += ` Error: ${fetchErrorDetail(fetchError)}.`
            }

            if (willRetry) {
                message += ` Retrying.`
            }

            addLog(isNonFailure ? 'info' : 'error', message)

            if (willRetry) {
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

        // Keep the status 500 fallback so template guards like `if (res.status
        // >= 400) throw` still fire on a client-side abort and prevent
        // subsequent fetches in multi-step templates from running against
        // broken assumptions. Populate body with the real client-side error
        // name and message so the terminal log stops reading as "status 500"
        // with an empty body and instead tells the customer what actually
        // happened (connect timeout, socket abort, DNS failure, etc.).
        const hogVmResponse: {
            status: number
            body: unknown
        } = {
            status: fetchResponse?.status ?? 500,
            body: body ?? (fetchError ? `${fetchError.name}: ${fetchErrorDetail(fetchError)}` : undefined),
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
}
