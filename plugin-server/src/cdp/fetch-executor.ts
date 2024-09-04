import { Histogram } from 'prom-client'

import { buildIntegerMatcher } from '../config/config'
import { PluginsServerConfig, ValueMatcher } from '../types'
import { trackedFetch } from '../utils/fetch'
import { status } from '../utils/status'
import { RustyHook } from '../worker/rusty-hook'
import {
    HogFunctionInvocation,
    HogFunctionInvocationAsyncRequest,
    HogFunctionInvocationResult,
    HogFunctionQueueParametersFetchRequest,
    HogFunctionQueueParametersFetchResponse,
} from './types'
import { gzipObject } from './utils'

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

/**
 * This class is only used by the kafka based queuing system. For the Cyclotron system there is no need for this.
 */
export class FetchExecutor {
    hogHookEnabledForTeams: ValueMatcher<number>

    constructor(private serverConfig: PluginsServerConfig, private rustyHook: RustyHook) {
        this.hogHookEnabledForTeams = buildIntegerMatcher(serverConfig.CDP_ASYNC_FUNCTIONS_RUSTY_HOOK_TEAMS, true)
    }

    async execute(invocation: HogFunctionInvocation): Promise<HogFunctionInvocationResult | undefined> {
        if (invocation.queue !== 'fetch' || !invocation.queueParameters) {
            throw new Error('Bad invocation')
        }

        const params = invocation.queueParameters as HogFunctionQueueParametersFetchRequest
        if (params.body) {
            histogramFetchPayloadSize.observe(params.body.length / 1024)
        }

        try {
            if (this.hogHookEnabledForTeams(invocation.teamId)) {
                // This is very temporary until we are commited to Cyclotron
                const payload: HogFunctionInvocationAsyncRequest = {
                    state: await gzipObject(invocation),
                    teamId: invocation.teamId,
                    hogFunctionId: invocation.hogFunction.id,
                    asyncFunctionRequest: {
                        name: 'fetch',
                        args: [
                            params.url,
                            {
                                ...params,
                            },
                        ],
                    },
                }
                const hoghooksPayload = JSON.stringify(payload)
                histogramHogHooksPayloadSize.observe(hoghooksPayload.length / 1024)
                const enqueued = await this.rustyHook.enqueueForHog(hoghooksPayload)
                if (enqueued) {
                    // We return nothing here hoghooks will take care of that
                    return
                }
            }

            status.info('🦔', `[HogExecutor] Webhook not sent via rustyhook, sending directly instead`)
        } catch (err) {
            status.error('🦔', `[HogExecutor] Error during fetch`, { error: String(err) })
        }

        return await this.executeLocally(invocation)
    }

    async executeLocally(invocation: HogFunctionInvocation): Promise<HogFunctionInvocationResult> {
        if (invocation.queue !== 'fetch' || !invocation.queueParameters) {
            throw new Error('Bad invocation')
        }

        const params = invocation.queueParameters as HogFunctionQueueParametersFetchRequest

        const resParams: HogFunctionQueueParametersFetchResponse = {
            response: {
                status: 0,
                body: {},
            },
            error: null,
            timings: [],
        }

        try {
            const start = performance.now()
            const fetchResponse = await trackedFetch(params.url, {
                method: params.method,
                body: params.body,
                headers: params.headers,
                timeout: this.serverConfig.EXTERNAL_REQUEST_TIMEOUT_MS,
            })

            let responseBody = await fetchResponse.text()
            try {
                responseBody = JSON.parse(responseBody)
            } catch (err) {
                // Ignore
            }

            const duration = performance.now() - start

            resParams.timings!.push({
                kind: 'async_function',
                duration_ms: duration,
            })

            resParams.response = {
                status: fetchResponse.status,
                body: responseBody,
            }
        } catch (err) {
            status.error('🦔', `[HogExecutor] Error during fetch`, { error: String(err) })
            resParams.error = 'Something went wrong with the fetch request.'
        }

        return {
            invocation: {
                ...invocation,
                queue: 'hog',
                queueParameters: resParams,
            },
            finished: false,
            logs: [],
        }
    }
}
