import cyclotron from 'cyclotron-node'
import { Histogram } from 'prom-client'

import { buildIntegerMatcher } from '../config/config'
import { PluginsServerConfig, ValueMatcher } from '../types'
import { trackedFetch } from '../utils/fetch'
import { status } from '../utils/status'
import { RustyHook } from '../worker/rusty-hook'
import { HogFunctionInvocationAsyncRequest, HogFunctionInvocationAsyncResponse } from './types'

export const BUCKETS_KB_WRITTEN = [0, 128, 512, 1024, 2024, 4096, 10240, Infinity]

const histogramFetchPayloadSize = new Histogram({
    name: 'cdp_async_function_fetch_payload_size_kb',
    help: 'The size in kb of the batches we are receiving from Kafka',
    buckets: BUCKETS_KB_WRITTEN,
})

const histogramHogHooksPayloadSize = new Histogram({
    name: 'cdp_async_function_hoghooks_payload_size_kb',
    help: 'The size in kb of the batches we are receiving from Kafka',
    buckets: BUCKETS_KB_WRITTEN,
})

export type AsyncFunctionExecutorOptions = {
    sync?: boolean
}

export class AsyncFunctionExecutor {
    hogHookEnabledForTeams: ValueMatcher<number>
    cyclotronEnabledForTeams: ValueMatcher<number>

    constructor(private serverConfig: PluginsServerConfig, private rustyHook: RustyHook) {
        this.hogHookEnabledForTeams = buildIntegerMatcher(serverConfig.CDP_ASYNC_FUNCTIONS_RUSTY_HOOK_TEAMS, true)
        this.cyclotronEnabledForTeams = buildIntegerMatcher(serverConfig.CDP_ASYNC_FUNCTIONS_CYCLOTRON_TEAMS, true)
    }

    async execute(
        request: HogFunctionInvocationAsyncRequest,
        options: AsyncFunctionExecutorOptions = { sync: false }
    ): Promise<HogFunctionInvocationAsyncResponse | undefined> {
        if (!request.asyncFunctionRequest) {
            throw new Error('No async function request provided')
        }

        const loggingContext = {
            hogFunctionId: request.hogFunctionId,
            asyncFunctionName: request.asyncFunctionRequest.name,
        }
        status.info('🦔', `[AsyncFunctionExecutor] Executing async function`, loggingContext)

        switch (request.asyncFunctionRequest.name) {
            // TODO: Add error case here - if we don't get a valid queued message then we should log something against the function
            case 'fetch':
                return await this.asyncFunctionFetch(request, options)
            default:
                status.error(
                    '🦔',
                    `[HogExecutor] Unknown async function: ${request.asyncFunctionRequest.name}`,
                    loggingContext
                )
        }
    }

    private async asyncFunctionFetch(
        request: HogFunctionInvocationAsyncRequest,
        options?: AsyncFunctionExecutorOptions
    ): Promise<HogFunctionInvocationAsyncResponse | undefined> {
        if (!request.asyncFunctionRequest) {
            return
        }

        const asyncFunctionResponse: HogFunctionInvocationAsyncResponse['asyncFunctionResponse'] = {
            response: null,
            timings: [],
        }

        try {
            // Sanitize the args
            const [url, fetchOptions] = request.asyncFunctionRequest.args as [
                string | undefined,
                Record<string, any> | undefined
            ]

            if (typeof url !== 'string') {
                status.error('🦔', `[HogExecutor] Invalid URL`, { ...request, url })
                return
            }

            const method = fetchOptions?.method || 'POST'
            const headers = fetchOptions?.headers || {
                'Content-Type': 'application/json',
            }
            let body = fetchOptions?.body
            // Modify the body to ensure it is a string (we allow Hog to send an object to keep things simple)
            body = body ? (typeof body === 'string' ? body : JSON.stringify(body)) : body

            // Finally overwrite the args with the sanitized ones
            request.asyncFunctionRequest.args = [url, { method, headers, body }]

            if (body) {
                histogramFetchPayloadSize.observe(body.length / 1024)
            }

            // If the caller hasn't forced it to be synchronous and the team has the cyclotron or
            // rustyhook enabled, enqueue it in one of those services.
            if (!options?.sync && this.cyclotronEnabledForTeams(request.teamId)) {
                try {
                    await cyclotron.createJob({
                        teamId: request.teamId,
                        functionId: request.hogFunctionId,
                        queueName: 'fetch',
                        // TODO: The async function compression changes happen upstream of this
                        // function. I guess we'll want to unwind that change because we actually
                        // want the `vmState` (and the rest of state) so we can put it into PG here.
                        vmState: '',
                        parameters: JSON.stringify({
                            return_queue: 'hog',
                            url,
                            method,
                            headers,
                            body,
                        }),
                        metadata: JSON.stringify({
                            // TODO: It seems like Fetch expects metadata to have this shape, which
                            // I don't understand. I think `metadata` is where all the other Hog
                            // state is going to be stored? For now I'm just trying to make fetch
                            // work.
                            tries: 0,
                            trace: [],
                        }),
                    })
                } catch (e) {
                    status.error(
                        '🦔',
                        `[HogExecutor] Cyclotron failed to enqueue async fetch function, sending directly instead`,
                        {
                            error: e,
                        }
                    )
                }
            } else if (!options?.sync && this.hogHookEnabledForTeams(request.teamId)) {
                const hoghooksPayload = JSON.stringify(request)

                histogramHogHooksPayloadSize.observe(hoghooksPayload.length / 1024)

                const enqueued = await this.rustyHook.enqueueForHog(JSON.stringify(request))
                if (enqueued) {
                    return
                }
            }

            status.info('🦔', `[HogExecutor] Webhook not sent via rustyhook, sending directly instead`)

            const start = performance.now()
            const fetchResponse = await trackedFetch(url, {
                method,
                body,
                headers,
                timeout: this.serverConfig.EXTERNAL_REQUEST_TIMEOUT_MS,
            })

            let responseBody = await fetchResponse.text()
            try {
                responseBody = JSON.parse(responseBody)
            } catch (err) {
                // Ignore
            }

            const duration = performance.now() - start

            asyncFunctionResponse.timings!.push({
                kind: 'async_function',
                duration_ms: duration,
            })

            asyncFunctionResponse.response = {
                status: fetchResponse.status,
                body: responseBody,
            }
        } catch (err) {
            status.error('🦔', `[HogExecutor] Error during fetch`, { error: String(err) })
            asyncFunctionResponse.error = 'Something went wrong with the fetch request.'
        }

        const response: HogFunctionInvocationAsyncResponse = {
            state: request.state,
            teamId: request.teamId,
            hogFunctionId: request.hogFunctionId,
            asyncFunctionResponse,
        }

        return response
    }
}
