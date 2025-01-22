import { DateTime } from 'luxon'

import { PluginsServerConfig } from '../../types'
import { trackedFetch } from '../../utils/fetch'
import { status } from '../../utils/status'
import {
    HogFunctionInvocation,
    HogFunctionInvocationResult,
    HogFunctionQueueParametersFetchRequest,
    HogFunctionQueueParametersFetchResponse,
} from '../types'

export class FetchExecutorService {
    constructor(private serverConfig: PluginsServerConfig) {}

    async executeLocally(invocation: HogFunctionInvocation): Promise<HogFunctionInvocationResult> {
        if (invocation.queue !== 'fetch' || !invocation.queueParameters) {
            throw new Error('Bad invocation')
        }

        const params = invocation.queueParameters as HogFunctionQueueParametersFetchRequest
        let responseBody = ''

        const resParams: HogFunctionQueueParametersFetchResponse = {
            response: {
                status: 0,
                headers: {},
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

            responseBody = await fetchResponse.text()

            const duration = performance.now() - start

            resParams.timings!.push({
                kind: 'async_function',
                duration_ms: duration,
            })

            // Emulates what the rust fetch service does - if error status, it will return an array of traces and no response
            if (fetchResponse.status && fetchResponse.status < 400) {
                resParams.response = {
                    status: fetchResponse.status,
                    headers: Object.fromEntries(fetchResponse.headers.entries()),
                }
            } else {
                resParams.trace = [
                    {
                        kind: 'failurestatus',
                        message: 'Received failure status',
                        headers: Object.fromEntries(fetchResponse.headers.entries()),
                        status: fetchResponse.status,
                        timestamp: DateTime.utc(),
                    },
                ]
            }

            resParams.body = responseBody
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
