import { DateTime } from 'luxon'
import { Histogram } from 'prom-client'
import { ReadableStream } from 'stream/web'

import { PluginsServerConfig } from '~/src/types'

import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import {
    fetch,
    FetchOptions,
    FetchResponse,
    InvalidRequestError,
    Response,
    SecureRequestError,
} from '../../utils/request'
import { LegacyPluginLogger } from '../legacy-plugins/types'
import { SEGMENT_DESTINATIONS_BY_ID } from '../segment/segment-templates'
import {
    CyclotronFetchFailureInfo,
    CyclotronFetchFailureKind,
    HogFunctionInvocation,
    HogFunctionInvocationResult,
    HogFunctionQueueParametersFetchRequest,
} from '../types'
import { CDP_TEST_ID, isSegmentPluginHogFunction } from '../utils'
import { createInvocationResult } from '../utils/invocation-utils'
import { RETRIABLE_STATUS_CODES } from './fetch-executor.service'
import { sanitizeLogMessage } from './hog-executor.service'

const pluginExecutionDuration = new Histogram({
    name: 'cdp_segment_execution_duration_ms',
    help: 'Processing time and success status of plugins',
    // We have a timeout so we don't need to worry about much more than that
    buckets: [0, 10, 20, 50, 100, 200],
})

class FetchError extends Error {
    fetchResponse: FetchResponse | null
    fetchError: any | undefined

    constructor(message?: string, fetchResponse?: FetchResponse | null, fetchError?: any) {
        super(message)
        this.fetchResponse = fetchResponse || null
        this.fetchError = fetchError
    }
}

export type SegmentPluginMeta = {
    config: Record<string, any>
    global: Record<string, any>
    logger: LegacyPluginLogger
}

// The module doesn't export this so we redeclare it here
export interface ModifiedResponse<T = unknown> extends Omit<Response, 'headers'> {
    content: string
    data: unknown extends T ? undefined | unknown : T
    headers: Headers & {
        toJSON: () => Record<string, string>
    }
}

const convertFetchResponse = async <Data = unknown>(response: FetchResponse): Promise<ModifiedResponse<Data>> => {
    const headers = new Headers() as ModifiedResponse['headers']
    Object.entries(response.headers).forEach(([key, value]) => {
        headers.set(key, value)
    })

    headers.toJSON = () => {
        return Object.fromEntries(headers.entries())
    }

    const text = await response.text()
    let json = undefined as Data

    try {
        json = parseJSON(text) as Data
    } catch {}

    const modifiedResponse: ModifiedResponse<Data> = {
        ...response,
        data: json,
        content: text,
        ok: response.status >= 200 && response.status < 300,
        redirected: response.status === 301 || response.status === 302,
        statusText: 'Status: ' + response.status,
        type: 'default',
        url: 'url',
        headers,
        body: new ReadableStream({
            start: (controller) => {
                controller.enqueue(new TextEncoder().encode(text))
                controller.close()
            },
        }),
        // NOTE: The majority of items below aren't used but we need to simulate their response type
        clone: () => modifiedResponse as unknown as Response,
        bodyUsed: false,
        arrayBuffer: () => {
            throw new Error('Not implemented')
        },
        blob: () => {
            throw new Error('Not implemented')
        },
        formData: () => {
            throw new Error('Not implemented')
        },
        json: () => response.json(),
    }

    return modifiedResponse
}

/**
 * NOTE: This is a consumer to take care of segment plugins.
 */

export class SegmentDestinationExecutorService {
    constructor(private serverConfig: PluginsServerConfig) {}

    public async fetch(...args: Parameters<typeof fetch>): Promise<FetchResponse> {
        return fetch(...args)
    }

    private handleFetchFailure(
        invocation: HogFunctionInvocation,
        response: FetchResponse | null,
        error: any | null
    ): HogFunctionInvocationResult | null {
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
        const maxTries = params?.max_tries ?? this.serverConfig.CDP_FETCH_RETRIES
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

            logger.info(`[SegmentExecutorService] Scheduling retry`, {
                hogFunctionId: invocation.hogFunction.id,
                status: failure.status,
                backoffMs,
                nextScheduledAt: nextScheduledAt.toISO(),
                retryCount: updatedMetadata.tries,
            })

            return createInvocationResult(
                invocation,
                {
                    queue: 'segment', // Keep in segment queue for retry
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
        return null
    }

    public async execute(invocation: HogFunctionInvocation): Promise<HogFunctionInvocationResult> {
        const result = createInvocationResult(invocation, {
            queue: 'segment',
        })

        const addLog = (level: 'debug' | 'warn' | 'error' | 'info', ...args: any[]) => {
            result.logs.push({
                level,
                timestamp: DateTime.now(),
                message: sanitizeLogMessage(args),
            })
        }

        const segmentDestinationId = isSegmentPluginHogFunction(invocation.hogFunction)
            ? invocation.hogFunction.template_id
            : null

        try {
            const segmentDestination = segmentDestinationId ? SEGMENT_DESTINATIONS_BY_ID[segmentDestinationId] : null

            if (!segmentDestination) {
                throw new Error(`Segment destination ${segmentDestinationId} not found`)
            }

            const isTestFunction = invocation.hogFunction.name.includes(CDP_TEST_ID)
            const start = performance.now()

            // All segment options are done as inputs
            const config = invocation.globals.inputs

            if (config.debug_mode) {
                addLog('debug', 'config', config)
            }

            const action = segmentDestination.destination.actions[config.internal_partner_action]

            if (!action) {
                throw new Error(`Action ${config.internal_partner_action} not found`)
            }

            await action.perform(
                // @ts-expect-error can't figure out unknown extends Data
                async (endpoint, options) => {
                    if (config.debug_mode) {
                        addLog('debug', 'endpoint', endpoint)
                    }
                    if (config.debug_mode) {
                        addLog('debug', 'options', options)
                    }
                    const requestExtension = segmentDestination.destination.extendRequest?.({
                        settings: config,
                        auth: config as any,
                        payload: config,
                    })
                    if (config.debug_mode) {
                        addLog('debug', 'requestExtension', requestExtension)
                    }
                    const headers: Record<string, string> = {
                        ...options?.headers,
                        ...requestExtension?.headers,
                    }
                    if (config.debug_mode) {
                        addLog('debug', 'headers', headers)
                    }

                    let body: string | undefined = undefined
                    if (options?.json) {
                        body = JSON.stringify(options.json)
                        headers['Content-Type'] = 'application/json'
                    } else if (options?.body && options.body instanceof URLSearchParams) {
                        body = options.body.toString()
                        headers['Content-Type'] = 'application/x-www-form-urlencoded'
                    } else if (options?.body && typeof options.body === 'string') {
                        body = options.body
                        headers['Content-Type'] = 'application/json'
                    }

                    const params = new URLSearchParams()
                    if (options?.searchParams && typeof options.searchParams === 'object') {
                        Object.entries(options.searchParams as Record<string, string>).forEach(([key, value]) =>
                            params.append(key, value)
                        )
                    }
                    if (requestExtension?.searchParams && typeof requestExtension.searchParams === 'object') {
                        Object.entries(requestExtension.searchParams as Record<string, string>).forEach(
                            ([key, value]) => params.append(key, value)
                        )
                    }

                    const fetchOptions: FetchOptions = {
                        method: options?.method?.toUpperCase() ?? 'GET',
                        headers,
                        body,
                    }

                    if (isTestFunction && options?.method?.toUpperCase() !== 'GET') {
                        // For testing we mock out all non-GET requests
                        addLog('info', 'Fetch called but mocked due to test function', {
                            url: endpoint,
                            options: fetchOptions,
                        })

                        result.metrics!.push({
                            team_id: invocation.hogFunction.team_id,
                            app_source_id: invocation.hogFunction.id,
                            metric_kind: 'other',
                            metric_name: 'fetch',
                            count: 1,
                        })
                        // Simulate a mini bit of fetch delay
                        await new Promise((resolve) => setTimeout(resolve, 200))
                        return convertFetchResponse({
                            status: 200,
                            headers: {},
                            json: () =>
                                Promise.resolve({
                                    status: 'OK',
                                    message: 'Test function',
                                }),
                            text: () =>
                                Promise.resolve(
                                    JSON.stringify({
                                        status: 'OK',
                                        message: 'Test function',
                                    })
                                ),
                        } as FetchResponse)
                    }

                    fetchOptions.headers = {
                        ...fetchOptions.headers,
                        endpoint: endpoint + '?' + params.toString(),
                    }

                    if (config.debug_mode) {
                        addLog('debug', 'fetchOptions', fetchOptions)
                    }

                    let fetchResponse: FetchResponse | null = null
                    let fetchError: any | undefined = undefined

                    try {
                        fetchResponse = await this.fetch(
                            `${endpoint}${params.toString() ? '?' + params.toString() : ''}`,
                            fetchOptions
                        )
                    } catch (err) {
                        fetchError = err
                    }

                    // If error - decide if it can be retried and set the values
                    if (!fetchResponse || (fetchResponse?.status && fetchResponse.status >= 400)) {
                        throw new FetchError(fetchError, fetchResponse)
                    }

                    const convertedResponse = await convertFetchResponse(fetchResponse)
                    if (config.debug_mode) {
                        addLog(
                            'debug',
                            'convertedResponse',
                            convertedResponse.status,
                            convertedResponse.data,
                            convertedResponse.content,
                            convertedResponse.body
                        )
                    }
                    return convertedResponse
                },
                {
                    payload: config,
                    settings: config,
                }
            )

            addLog('info', `Function completed in ${performance.now() - start}ms.`)

            pluginExecutionDuration.observe(performance.now() - start)
        } catch (e) {
            let errorMessage = e
            if (e instanceof FetchError) {
                const retryResult = this.handleFetchFailure(invocation, e.fetchResponse, e.fetchError)
                if (retryResult) {
                    return retryResult
                }
                errorMessage = `Request failed with status ${
                    e.fetchResponse?.status
                } (${await e.fetchResponse?.text()})`
            }

            logger.error('💩', 'Segment destination errored', {
                error: e.message,
                segmentDestinationId,
                invocationId: invocation.id,
            })

            result.error = e

            addLog(
                'error',
                `Error executing function on event ${
                    invocation?.globals?.event?.uuid || 'Unknown event'
                }: ${errorMessage}`
            )
        }

        return result
    }
}
