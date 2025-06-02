import { DateTime } from 'luxon'
import { Histogram } from 'prom-client'
import { ReadableStream } from 'stream/web'

import { PluginsServerConfig } from '~/src/types'
import { tryCatch } from '~/src/utils/try-catch'

import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { fetch, FetchOptions, FetchResponse, Response } from '../../utils/request'
import { LegacyPluginLogger } from '../legacy-plugins/types'
import { SEGMENT_DESTINATIONS_BY_ID } from '../segment/segment-templates'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { CDP_TEST_ID, isSegmentPluginHogFunction } from '../utils'
import { createInvocationResult } from '../utils/invocation-utils'
import { getNextRetryTime, isFetchResponseRetriable } from './fetch-executor.service'
import { sanitizeLogMessage } from './hog-executor.service'

const pluginExecutionDuration = new Histogram({
    name: 'cdp_segment_execution_duration_ms',
    help: 'Processing time and success status of plugins',
    // We have a timeout so we don't need to worry about much more than that
    buckets: [0, 10, 20, 50, 100, 200],
})

class SegmentRetriableError extends Error {
    constructor(message?: string) {
        super(message)
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

    public async execute(
        invocation: CyclotronJobInvocationHogFunction
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        const result = createInvocationResult<CyclotronJobInvocationHogFunction>(invocation, {
            queue: 'segment',
        })

        // Upsert the tries count on the metadata
        const metadata = (invocation.queueMetadata as { tries: number }) || { tries: 0 }
        metadata.tries = metadata.tries + 1
        result.invocation.queueMetadata = metadata

        // Indicates if a retry is possible. Once we have peformed 1 successful non-GET request, we can't retry.
        let retriesPossible = true

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
            const config = invocation.state.globals.inputs

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

                    const method = options?.method?.toUpperCase() ?? 'GET'

                    const fetchOptions: FetchOptions = {
                        method,
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

                    if (config.debug_mode) {
                        addLog('debug', 'fetchOptions', fetchOptions)
                    }

                    const [fetchError, fetchResponse] = await tryCatch(() =>
                        this.fetch(`${endpoint}${params.toString() ? '?' + params.toString() : ''}`, fetchOptions)
                    )

                    if (
                        retriesPossible &&
                        isFetchResponseRetriable(fetchResponse, fetchError) &&
                        metadata.tries < this.serverConfig.CDP_FETCH_RETRIES
                    ) {
                        // If we it is retriable and we have retries left, we can trigger a retry, otherwise we just pass through to the function
                        addLog(
                            'info',
                            `HTTP request failed with status ${fetchResponse?.status ?? 'unknown'}. Scheduling retry...`
                        )
                        throw new SegmentRetriableError()
                    }

                    if (method !== 'GET') {
                        // If we have got to this point with anything other than a GET request, we can't retry for the risk of duplicating data
                        // as retries apply to the entire invocation, not just the http request.
                        retriesPossible = false
                    }

                    if (!fetchResponse) {
                        throw new Error('HTTP request failed')
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
            if (e instanceof SegmentRetriableError) {
                // We have retries left so we can trigger a retry
                result.finished = false
                result.invocation.queue = 'segment'
                result.invocation.queuePriority = metadata.tries
                result.invocation.queueScheduledAt = getNextRetryTime(this.serverConfig, metadata.tries)
            }

            logger.error('💩', 'Segment destination errored', {
                error: e.message,
                segmentDestinationId,
                invocationId: invocation.id,
            })

            result.error = e

            addLog('error', `Function failed: ${e.message}`)
        }

        return result
    }
}
