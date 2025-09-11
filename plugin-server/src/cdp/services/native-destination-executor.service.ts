import { Histogram } from 'prom-client'

import { PluginsServerConfig } from '~/types'
import { parseJSON } from '~/utils/json-parse'

import { logger } from '../../utils/logger'
import { FetchOptions, FetchResponse } from '../../utils/request'
import { NATIVE_HOG_FUNCTIONS_BY_ID } from '../templates'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, Response } from '../types'
import { CDP_TEST_ID, createAddLogFunction, isNativeHogFunction } from '../utils'
import { createInvocationResult } from '../utils/invocation-utils'
import { cdpTrackedFetch, getNextRetryTime, isFetchResponseRetriable } from './hog-executor.service'

const nativeDestinationExecutionDuration = new Histogram({
    name: 'cdp_native_execution_duration_ms',
    help: 'Processing time and success status of native plugins',
    // We have a timeout so we don't need to worry about much more than that
    buckets: [0, 10, 20, 50, 100, 200],
})

class FetchError extends Error {
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

    public async execute(
        invocation: CyclotronJobInvocationHogFunction
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        const result = createInvocationResult<CyclotronJobInvocationHogFunction>(invocation)
        const addLog = createAddLogFunction(result.logs)

        // Upsert the tries count on the metadata
        const metadata = (invocation.queueMetadata as { tries: number }) || { tries: 0 }
        metadata.tries = metadata.tries + 1
        result.invocation.queueMetadata = metadata

        // Indicates if a retry is possible. Once we have peformed 1 successful non-GET request, we can't retry.
        let retriesPossible = true

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

            // All native plugin options are done as inputs
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

                    const headers: Record<string, any> = {
                        'User-Agent': 'PostHog.com/1.0',
                        ...options.headers,
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

                        result.metrics.push({
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

                    const url = `${endpoint}${params.toString() ? '?' + params.toString() : ''}`
                    const { fetchError, fetchResponse } = await cdpTrackedFetch({
                        url,
                        fetchParams: fetchOptions,
                        templateId: invocation.hogFunction.template_id ?? '',
                    })

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
                            throw new FetchError(
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
                    payload: config,
                }
            )

            addLog('info', `Function completed in ${performance.now() - start}ms.`)

            nativeDestinationExecutionDuration.observe(performance.now() - start)
        } catch (e) {
            if (e instanceof FetchError) {
                if (retriesPossible) {
                    // We have retries left so we can trigger a retry
                    result.finished = false
                    result.invocation.queue = 'hog'
                    result.invocation.queuePriority = metadata.tries
                    result.invocation.queueScheduledAt = getNextRetryTime(this.serverConfig, metadata.tries)
                    return result
                } else {
                    result.finished = true
                }
            }

            logger.error('💩', 'Native destination errored', {
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
