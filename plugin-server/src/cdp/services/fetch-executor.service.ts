import { Liquid } from 'liquidjs'
import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { PluginsServerConfig } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { fetch, FetchOptions, FetchResponse, InvalidRequestError, SecureRequestError } from '../../utils/request'
import { tryCatch } from '../../utils/try-catch'
import {
    CyclotronFetchFailureInfo,
    CyclotronFetchFailureKind,
    CyclotronJobInvocation,
    CyclotronJobInvocationResult,
    HogFunctionQueueParametersFetchRequest,
} from '../types'
import { createInvocationResult } from '../utils/invocation-utils'

const cdpHttpRequests = new Counter({
    name: 'cdp_http_requests',
    help: 'HTTP requests and their outcomes',
    labelNames: ['status'],
})

export const RETRIABLE_STATUS_CODES = [
    408, // Request Timeout
    429, // Too Many Requests (rate limiting)
    500, // Internal Server Error
    502, // Bad Gateway
    503, // Service Unavailable
    504, // Gateway Timeout
]

const parseLiquidTemplate = (
    template: string,
    context: any,
    inputs?: Record<string, any>,
    allowLiquid: boolean = false
): string => {
    // Early return if liquid processing is disabled
    if (!allowLiquid) {
        logger.info('🔍 Liquid parsing disabled', { template, allowLiquid })
        return template
    }

    try {
        const liquid = new Liquid({
            strictFilters: false,
            strictVariables: false,
            outputEscape: 'escape',
        })

        // Register custom filters
        liquid.registerFilter('default', (value: any, defaultValue: any) => value ?? defaultValue)
        liquid.registerFilter('date', (value: any, format: string) => {
            // Handle "now" as current date
            const date = value === 'now' ? new Date() : new Date(value)

            // Simple date formatting - you can expand this
            if (format === '%Y%m%d') {
                return (
                    date.getFullYear().toString() +
                    (date.getMonth() + 1).toString().padStart(2, '0') +
                    date.getDate().toString().padStart(2, '0')
                )
            }
            if (format === '%B %-d, %Y at %l:%M %p') {
                return (
                    date.toLocaleDateString('en-US', {
                        month: 'long',
                        day: 'numeric',
                        year: 'numeric',
                    }) +
                    ' at ' +
                    date.toLocaleTimeString('en-US', {
                        hour: 'numeric',
                        minute: '2-digit',
                        hour12: true,
                    })
                )
            }
            if (format === '%l:%M %p') {
                return date.toLocaleTimeString('en-US', {
                    hour: 'numeric',
                    minute: '2-digit',
                    hour12: true,
                })
            }
            // Fallback to ISO string
            return date.toISOString()
        })

        // HTML decode the template before processing. To do maybe we should use a library for better html decoding
        // $ is not decoded because it is used as a variable in liquid templates, so we need to handle this separately
        const decodedTemplate = template
            .replace(/&gt;/g, '>')
            .replace(/&lt;/g, '<')
            .replace(/&amp;/g, '&')
            .replace(/&quot;/g, '"')
            .replace(/&#x27;/g, "'")

        const liquidContext = {
            event: context.event,
            person: context.person,
            groups: context.groups,
            project: context.project,
            source: context.source,
            inputs: inputs || {},
            now: new Date(),
        }

        const result = liquid.parseAndRenderSync(decodedTemplate, liquidContext)

        return result
    } catch (error) {
        logger.warn('🔍 Liquid template parsing failed', {
            error: error.message,
            template,
            stack: error.stack,
        })
        return template
    }
}

export const isFetchResponseRetriable = (response: FetchResponse | null, error: any | null): boolean => {
    let canRetry = !!response?.status && RETRIABLE_STATUS_CODES.includes(response.status)

    if (error) {
        if (error instanceof SecureRequestError || error instanceof InvalidRequestError) {
            canRetry = false
        } else {
            canRetry = true // Only retry on general errors, not security or validation errors
        }
    }

    return canRetry
}

export const getNextRetryTime = (config: PluginsServerConfig, tries: number): DateTime => {
    const backoffMs = Math.min(
        config.CDP_FETCH_BACKOFF_BASE_MS * tries + Math.floor(Math.random() * config.CDP_FETCH_BACKOFF_BASE_MS),
        config.CDP_FETCH_BACKOFF_MAX_MS
    )
    return DateTime.utc().plus({ milliseconds: backoffMs })
}

export class FetchExecutorService {
    constructor(private serverConfig: PluginsServerConfig) {}

    private async handleFetchFailure(
        invocation: CyclotronJobInvocation,
        response: FetchResponse | null,
        error: any | null
    ): Promise<CyclotronJobInvocationResult> {
        let kind: CyclotronFetchFailureKind = 'requesterror'

        if (error?.message.toLowerCase().includes('timeout')) {
            kind = 'timeout'
        }

        const failure: CyclotronFetchFailureInfo = response
            ? {
                  kind: 'failurestatus' as CyclotronFetchFailureKind,
                  message: `Received failure status: ${response?.status}`,
                  headers: response?.headers,
                  status: response?.status,
                  timestamp: DateTime.utc(),
              }
            : {
                  kind: kind,
                  message: String(error),
                  timestamp: DateTime.utc(),
              }

        // Get existing metadata from previous attempts if any
        const metadata = (invocation.queueMetadata as { tries: number; trace: CyclotronFetchFailureInfo[] }) || {
            tries: 0,
            trace: [],
        }
        const params = invocation.queueParameters as HogFunctionQueueParametersFetchRequest
        const maxTries = params.max_tries ?? this.serverConfig.CDP_FETCH_RETRIES
        const updatedMetadata = {
            tries: metadata.tries + 1,
            trace: [...metadata.trace, failure],
        }

        const canRetry = isFetchResponseRetriable(response, error)

        // If we haven't exceeded retry limit, schedule a retry with backoff
        if (canRetry && updatedMetadata.tries < maxTries) {
            // Calculate backoff with jitter, similar to Rust implementation
            const backoffMs = Math.min(
                this.serverConfig.CDP_FETCH_BACKOFF_BASE_MS * updatedMetadata.tries +
                    Math.floor(Math.random() * this.serverConfig.CDP_FETCH_BACKOFF_BASE_MS),
                this.serverConfig.CDP_FETCH_BACKOFF_MAX_MS
            )

            const nextScheduledAt = DateTime.utc().plus({ milliseconds: backoffMs })

            logger.info(`[FetchExecutorService] Scheduling retry`, {
                functionId: invocation.functionId,
                status: failure.status,
                backoffMs,
                nextScheduledAt: nextScheduledAt.toISO(),
                retryCount: updatedMetadata.tries,
            })

            return createInvocationResult(
                invocation,
                {
                    queue: 'fetch', // Keep in fetch queue for retry
                    queueMetadata: updatedMetadata,
                    queueParameters: invocation.queueParameters, // Keep the same parameters
                    queuePriority: invocation.queuePriority + 1, // Decrease priority for retries
                    queueScheduledAt: nextScheduledAt,
                },
                {
                    finished: false,
                }
            )
        }

        // If we've exceeded retries, return all failures in trace
        return createInvocationResult(
            invocation,
            {
                queue: params.return_queue,
                queueParameters: {
                    response: response
                        ? {
                              status: response?.status,
                              headers: response?.headers,
                          }
                        : null,
                    body: response ? await response.text() : null,
                    trace: updatedMetadata.trace,
                    timings: [],
                },
            },
            {
                finished: false,
                metrics: [
                    {
                        team_id: invocation.teamId,
                        app_source_id: invocation.functionId,
                        metric_kind: 'other',
                        metric_name: 'fetch',
                        count: 1,
                    },
                ],
            }
        )
    }

    async execute(invocation: CyclotronJobInvocation): Promise<CyclotronJobInvocationResult> {
        if (invocation.queue !== 'fetch' || !invocation.queueParameters) {
            throw new Error('Bad invocation')
        }

        const start = performance.now()
        const params = invocation.queueParameters as HogFunctionQueueParametersFetchRequest
        const method = params.method.toUpperCase()

        // Check if this is an email request (Mailjet or other email providers, we can add more later)
        const isEmailRequest = params.url.includes('mailjet') || params.url.includes('sendgrid')

        let processedBody = params.body

        // If it's an email request, parse liquid templates
        if (isEmailRequest && params.body) {
            try {
                const bodyData = typeof params.body === 'string' ? parseJSON(params.body) : params.body

                // Check for liquid setting in multiple places:
                // 1. Template-level setting
                // 2. Input-level setting
                // 3. Schema-level setting (templating: false means liquid enabled)
                const templateAllowLiquid = invocation.hogFunction.template?.allowLiquid || false
                const inputAllowLiquid = invocation.globals.inputs?.allowLiquid || false

                // Check if any email input schema has templating disabled (which means liquid enabled)
                const emailSchemas = invocation.hogFunction.inputs_schema?.filter((s) => s.type === 'email') || []
                const schemaAllowLiquid = emailSchemas.some((s) => s.templating === false)

                const allowLiquid = templateAllowLiquid || inputAllowLiquid || schemaAllowLiquid

                logger.info('🐕', `[FetchExecutor] Processing email with liquid templates`, {
                    hogFunctionId: invocation.hogFunction.id,
                    allowLiquid,
                    templateAllowLiquid,
                    inputAllowLiquid,
                    schemaAllowLiquid,
                    emailSchemas: emailSchemas.map((s) => ({ key: s.key, templating: s.templating })),
                })

                // Process email fields that might contain liquid templates
                if (bodyData.Messages) {
                    // Mailjet format
                    bodyData.Messages = bodyData.Messages.map((message: any) => ({
                        ...message,
                        Subject: message.Subject
                            ? parseLiquidTemplate(
                                  message.Subject,
                                  invocation.globals,
                                  invocation.globals.inputs,
                                  allowLiquid
                              )
                            : message.Subject,
                        HTMLPart: message.HTMLPart
                            ? parseLiquidTemplate(
                                  message.HTMLPart,
                                  invocation.globals,
                                  invocation.globals.inputs,
                                  allowLiquid
                              )
                            : message.HTMLPart,
                        TextPart: message.TextPart
                            ? parseLiquidTemplate(
                                  message.TextPart,
                                  invocation.globals,
                                  invocation.globals.inputs,
                                  allowLiquid
                              )
                            : message.TextPart,
                    }))
                }

                processedBody = JSON.stringify(bodyData)
            } catch (error) {
                logger.warn('Failed to process email liquid templates', {
                    error: error.message,
                    hogFunctionId: invocation.hogFunction.id,
                })
                // Continue with original body if parsing fails
            }
        }

        const fetchParams: FetchOptions = {
            method,
            headers: params.headers,
            timeoutMs: this.serverConfig.CDP_FETCH_TIMEOUT_MS,
        }

        if (!['GET', 'HEAD'].includes(method) && processedBody) {
            fetchParams.body = processedBody
        }

        const [fetchError, fetchResponse] = await tryCatch(async () => await fetch(params.url, fetchParams))

        const duration = performance.now() - start
        cdpHttpRequests.inc({ status: fetchResponse?.status?.toString() ?? 'error' })

        // If error - decide if it can be retried and set the values
        if (!fetchResponse || (fetchResponse?.status && fetchResponse.status >= 400)) {
            return await this.handleFetchFailure(invocation, fetchResponse, fetchError)
        }

        return createInvocationResult(
            invocation,
            {
                queue: params.return_queue,
                queueParameters: {
                    response: {
                        status: fetchResponse?.status,
                        headers: fetchResponse?.headers,
                    },
                    body: await fetchResponse.text(),
                    timings: [
                        {
                            kind: 'async_function',
                            duration_ms: duration,
                        },
                    ],
                },
            },
            {
                finished: false,
                metrics: [
                    {
                        team_id: invocation.teamId,
                        app_source_id: invocation.functionId,
                        metric_kind: 'other',
                        metric_name: 'fetch',
                        count: 1,
                    },
                ],
            }
        )
    }
}
