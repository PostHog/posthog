import { DateTime } from 'luxon'
import { FetchError, RequestInit } from 'node-fetch'

import { PluginsServerConfig } from '../../types'
import { trackedFetch } from '../../utils/fetch'
import {
    CyclotronFetchFailureInfo,
    CyclotronFetchFailureKind,
    HogFunctionInvocation,
    HogFunctionInvocationResult,
    HogFunctionQueueParametersFetchRequest,
} from '../types'

/**
 * This class is only used by the kafka based queuing system. For the Cyclotron system there is no need for this.
 */
export class FetchExecutorService {
    constructor(private serverConfig: PluginsServerConfig) {}

    private handleFetchFailure(
        invocation: HogFunctionInvocation,
        failure: CyclotronFetchFailureInfo,
        metadata: { tries: number; trace: CyclotronFetchFailureInfo[] } = { tries: 0, trace: [] }
    ): HogFunctionInvocationResult {
        const params = invocation.queueParameters as HogFunctionQueueParametersFetchRequest
        const maxTries = params.max_tries ?? this.serverConfig.CDP_FETCH_RETRIES
        const updatedMetadata = {
            tries: metadata.tries + 1,
            trace: [...metadata.trace, failure],
        }

        // If we haven't exceeded retry limit, schedule a retry with backoff
        if (updatedMetadata.tries < maxTries) {
            // Calculate backoff with jitter, similar to Rust implementation
            const backoffMs = Math.min(
                this.serverConfig.CDP_FETCH_BACKOFF_BASE_MS * updatedMetadata.tries +
                    Math.floor(Math.random() * this.serverConfig.CDP_FETCH_BACKOFF_BASE_MS),
                this.serverConfig.CDP_FETCH_BACKOFF_MAX_MS
            )

            const nextScheduledAt = DateTime.utc().plus({ milliseconds: backoffMs })

            return {
                invocation: {
                    ...invocation,
                    queue: 'fetch', // Keep in fetch queue for retry
                    queueMetadata: updatedMetadata,
                    queuePriority: invocation.queuePriority + 1, // Decrease priority for retries
                    queueScheduledAt: nextScheduledAt,
                },
                finished: false,
                logs: [],
            }
        }

        // If we've exceeded retries, return all failures in trace
        return {
            invocation: {
                ...invocation,
                queue: 'hog',
                queueParameters: {
                    response: null,
                    trace: updatedMetadata.trace,
                    timings: [],
                },
            },
            finished: false,
            logs: [],
        }
    }

    async execute(invocation: HogFunctionInvocation): Promise<HogFunctionInvocationResult> {
        if (invocation.queue !== 'fetch' || !invocation.queueParameters) {
            throw new Error('Bad invocation')
        }

        const params = invocation.queueParameters as HogFunctionQueueParametersFetchRequest
        let responseBody = ''

        // Get existing metadata from previous attempts if any
        const metadata = (invocation.queueMetadata as { tries: number; trace: CyclotronFetchFailureInfo[] }) || {
            tries: 0,
            trace: [],
        }

        try {
            const start = performance.now()
            const method = params.method.toUpperCase()
            const fetchParams: RequestInit = {
                method,
                headers: params.headers,
                timeout: this.serverConfig.CDP_FETCH_TIMEOUT_MS,
            }
            if (!['GET', 'HEAD'].includes(method) && params.body) {
                fetchParams.body = params.body
            }
            const fetchResponse = await trackedFetch(params.url, fetchParams)

            responseBody = await fetchResponse.text()

            const duration = performance.now() - start
            const headers = Object.fromEntries(fetchResponse.headers.entries())

            // Match Rust implementation: Only return response for success status codes (<400)
            if (fetchResponse.status && fetchResponse.status < 400) {
                return {
                    invocation: {
                        ...invocation,
                        queue: 'hog',
                        queueParameters: {
                            response: {
                                status: fetchResponse.status,
                                headers,
                            },
                            body: responseBody,
                            timings: [
                                {
                                    kind: 'async_function',
                                    duration_ms: duration,
                                },
                            ],
                        },
                    },
                    finished: false,
                    logs: [],
                }
            } else {
                // For failure status codes, handle retry logic
                const failure: CyclotronFetchFailureInfo = {
                    kind: 'failurestatus' as CyclotronFetchFailureKind,
                    message: `Received failure status: ${fetchResponse.status}`,
                    headers,
                    status: fetchResponse.status,
                    timestamp: DateTime.utc(),
                }
                return this.handleFetchFailure(invocation, failure, metadata)
            }
        } catch (err) {
            let kind: CyclotronFetchFailureKind = 'requesterror'

            if (err instanceof FetchError) {
                if (err.type === 'request-timeout') {
                    kind = 'timeout'
                }
            }

            // Match Rust implementation: Create a failure trace for errors
            const failure: CyclotronFetchFailureInfo = {
                kind,
                message: String(err),
                timestamp: DateTime.utc(),
            }
            return this.handleFetchFailure(invocation, failure, metadata)
        }
    }
}
