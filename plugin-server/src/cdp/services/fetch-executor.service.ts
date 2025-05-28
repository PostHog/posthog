import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { PluginsServerConfig } from '../../types'
import { logger } from '../../utils/logger'
import { fetch, FetchOptions, FetchResponse, InvalidRequestError, SecureRequestError } from '../../utils/request'
import {
    CyclotronFetchFailureInfo,
    CyclotronFetchFailureKind,
    HogFunctionInvocation,
    HogFunctionInvocationResult,
    HogFunctionQueueParametersFetchRequest,
} from '../types'
import { createInvocationResult } from '../utils/invocation-utils'

const cdpHttpRequests = new Counter({
    name: 'cdp_http_requests',
    help: 'HTTP requests and their outcomes',
    labelNames: ['status'],
})

const RETRIABLE_STATUS_CODES = [
    408, // Request Timeout
    429, // Too Many Requests (rate limiting)
    500, // Internal Server Error
    502, // Bad Gateway
    503, // Service Unavailable
    504, // Gateway Timeout
]

export class FetchExecutorService {
    constructor(private serverConfig: PluginsServerConfig) {}

    private async handleFetchFailure(
        invocation: HogFunctionInvocation,
        response: FetchResponse | null,
        error: any | null
    ): Promise<HogFunctionInvocationResult> {
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

        let canRetry = !!response?.status && RETRIABLE_STATUS_CODES.includes(response.status)

        if (error) {
            if (error instanceof SecureRequestError || error instanceof InvalidRequestError) {
                canRetry = false
            } else {
                canRetry = true // Only retry on general errors, not security or validation errors
            }
        }

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
                hogFunctionId: invocation.hogFunction.id,
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
                queue: 'hog',
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
                        app_source_id: invocation.hogFunction.id,
                        metric_kind: 'other',
                        metric_name: 'fetch',
                        count: 1,
                    },
                ],
            }
        )
    }

    async execute(invocation: HogFunctionInvocation): Promise<HogFunctionInvocationResult> {
        if (invocation.queue !== 'fetch' || !invocation.queueParameters) {
            throw new Error('Bad invocation')
        }

        const start = performance.now()
        const params = invocation.queueParameters as HogFunctionQueueParametersFetchRequest
        const method = params.method.toUpperCase()
        const fetchParams: FetchOptions = {
            method,
            headers: params.headers,
            timeoutMs: this.serverConfig.CDP_FETCH_TIMEOUT_MS,
        }
        if (!['GET', 'HEAD'].includes(method) && params.body) {
            fetchParams.body = params.body
        }

        let fetchResponse: FetchResponse | null = null
        let fetchError: any | undefined = undefined

        try {
            fetchResponse = await fetch(params.url, fetchParams)
        } catch (err) {
            fetchError = err
        }

        const duration = performance.now() - start
        cdpHttpRequests.inc({ status: fetchResponse?.status?.toString() ?? 'error' })

        // If error - decide if it can be retried and set the values
        if (!fetchResponse || (fetchResponse?.status && fetchResponse.status >= 400)) {
            return await this.handleFetchFailure(invocation, fetchResponse, fetchError)
        }

        return createInvocationResult(
            invocation,
            {
                queue: 'hog',
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
                        app_source_id: invocation.hogFunction.id,
                        metric_kind: 'other',
                        metric_name: 'fetch',
                        count: 1,
                    },
                ],
            }
        )
    }
}
