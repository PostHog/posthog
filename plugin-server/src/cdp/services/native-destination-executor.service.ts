import { DateTime } from 'luxon'
import { Histogram } from 'prom-client'

import { PluginsServerConfig } from '~/types'

import { logger } from '../../utils/logger'
import { fetch, FetchOptions, FetchResponse } from '../../utils/request'
import { tryCatch } from '../../utils/try-catch'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../types'
import { CDP_TEST_ID, isNativeHogFunction } from '../utils'
import { createInvocationResult } from '../utils/invocation-utils'
import { getNextRetryTime, isFetchResponseRetriable } from './hog-executor.service'
import { sanitizeLogMessage } from './hog-executor.service'
import { HogFunctionTemplate } from '../templates/types'
import { parseJSON } from '~/utils/json-parse'
import { NATIVE_HOG_FUNCTIONS_BY_ID } from '../templates'

export type Response = {
    status: number,
    data: string,
    content: string,
    headers: Record<string, any>,
}

export type NativeTemplate = Omit<HogFunctionTemplate, 'hog'> & {
    perform: (request: (url: string, options: {
        method?: 'POST' | 'GET' | 'PATCH' | 'PUT' | 'DELETE'
        headers: Record<string, any>
        json?: any
        body?: string | URLSearchParams
        throwHttpErrors?: boolean
        searchParams?: Record<string, any>
    }) => Promise<Response>, 
    inputs: Record<string, any>) => Response
}

const pluginExecutionDuration = new Histogram({
    name: 'cdp_native_execution_duration_ms',
    help: 'Processing time and success status of native plugins',
    // We have a timeout so we don't need to worry about much more than that
    buckets: [0, 10, 20, 50, 100, 200],
})

class SegmentFetchError extends Error {
    constructor(message?: string) {
        super(message)
    }
}

const convertFetchResponse = (response: FetchResponse, text: string): Response => {
    let json = undefined

    try {
        json = parseJSON(text)
    } catch {}

    const modifiedResponse = {
        status: response.status,
        data: json,
        content: text,
        headers: response.headers,
    }

    return modifiedResponse
}

/**
 * NOTE: This is a consumer to take care of native plugins.
 */

export class NativeDestinationExecutorService {
    constructor(private serverConfig: PluginsServerConfig) {}

    public async fetch(...args: Parameters<typeof fetch>): Promise<FetchResponse> {
        return fetch(...args)
    }

    public async execute(
        invocation: CyclotronJobInvocationHogFunction
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        const result = createInvocationResult<CyclotronJobInvocationHogFunction>(invocation)

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

        const nativeDestinationId = isNativeHogFunction(invocation.hogFunction)
            ? invocation.hogFunction.template_id
            : null

        try {
            const nativeDestination = nativeDestinationId ? NATIVE_HOG_FUNCTIONS_BY_ID[nativeDestinationId] : null

            if (!nativeDestination) {
                throw new Error(`Native destination ${nativeDestinationId} not found`)
            }

            const isTestFunction = invocation.hogFunction.name.includes(CDP_TEST_ID)
            const start = performance.now()

            // All segment options are done as inputs
            const config = invocation.state.globals.inputs

            if (config.debug_mode) {
                addLog('debug', 'config', config)
            }

            await nativeDestination.perform(
                async (endpoint, options) => {

                    if (config.debug_mode) {
                        addLog('debug', 'endpoint', endpoint)
                    }
                    if (config.debug_mode) {
                        addLog('debug', 'options', options)
                    }

                    let headers: Record<string, any> = {
                        ...options.headers
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
                        return convertFetchResponse(
                            {
                                status: 200,
                                headers: {},
                            } as FetchResponse,
                            JSON.stringify({
                                status: 'OK',
                                message: 'Test function',
                            })
                        )
                    }

                    if (config.debug_mode) {
                        addLog('debug', 'fetchOptions', fetchOptions)
                    }

                    const [fetchError, fetchResponse] = await tryCatch(() =>
                        this.fetch(`${endpoint}${params.toString() ? '?' + params.toString() : ''}`, fetchOptions)
                    )
                    const fetchResponseText = (await fetchResponse?.text()) ?? 'unknown'

                    if (fetchError || !fetchResponse || fetchResponse.status >= 400) {
                        if (
                            !(
                                retriesPossible &&
                                isFetchResponseRetriable(fetchResponse, fetchError) &&
                                metadata.tries < this.serverConfig.CDP_FETCH_RETRIES
                            )
                        ) {
                            retriesPossible = false
                        }
                        addLog(
                            'warn',
                            `HTTP request failed with status ${fetchResponse?.status} (${
                                fetchResponseText ?? 'unknown'
                            }). ${retriesPossible ? 'Scheduling retry...' : ''}`
                        )

                        // If it's retriable and we have retries left, we can trigger a retry, otherwise we just pass through to the function
                        if (retriesPossible || (options?.throwHttpErrors ?? true)) {
                            throw new SegmentFetchError(
                                `Error executing function on event ${
                                    invocation.state.globals.event.uuid
                                }: Request failed with status ${fetchResponse?.status} (${
                                    fetchResponseText ?? 'unknown'
                                })`
                            )
                        }
                    }

                    if (method !== 'GET') {
                        // If we have got to this point with anything other than a GET request, we can't retry for the risk of duplicating data
                        // as retries apply to the entire invocation, not just the http request.
                        retriesPossible = false
                    }

                    if (!fetchResponse) {
                        throw new Error('HTTP request failed')
                    }

                    const convertedResponse = convertFetchResponse(fetchResponse, fetchResponseText)
                    if (config.debug_mode) {
                        addLog(
                            'debug',
                            'convertedResponse',
                            convertedResponse.status,
                            convertedResponse.data,
                            convertedResponse.content,
                            convertedResponse.headers
                        )
                    }
                    return convertedResponse
                },
                {
                    payload: invocation.state.globals.inputs
                }
            )

            addLog('info', `Function completed in ${performance.now() - start}ms.`)

            pluginExecutionDuration.observe(performance.now() - start)
        } catch (e) {
            if (e instanceof SegmentFetchError) {
                if (retriesPossible) {
                    // We have retries left so we can trigger a retry
                    result.finished = false
                    result.invocation.queue = 'segment'
                    result.invocation.queuePriority = metadata.tries
                    result.invocation.queueScheduledAt = getNextRetryTime(this.serverConfig, metadata.tries)
                    return result
                } else {
                    result.finished = true
                }
            }

            logger.error('💩', 'Segment destination errored', {
                error: e.message,
                nativeDestinationId,
                invocationId: invocation.id,
            })

            result.error = e

            addLog('error', `Function failed: ${e.message}`)
        }

        return result
    }
}
