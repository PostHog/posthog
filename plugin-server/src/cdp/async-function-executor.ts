import { buildIntegerMatcher } from '../config/config'
import { PluginsServerConfig, ValueMatcher } from '../types'
import { trackedFetch } from '../utils/fetch'
import { status } from '../utils/status'
import { RustyHook } from '../worker/rusty-hook'
import { HogFunctionInvocationAsyncResponse, HogFunctionInvocationResult } from './types'

export type AsyncFunctionExecutorOptions = {
    sync?: boolean
}

export class AsyncFunctionExecutor {
    hogHookEnabledForTeams: ValueMatcher<number>

    constructor(private serverConfig: PluginsServerConfig, private rustyHook: RustyHook) {
        this.hogHookEnabledForTeams = buildIntegerMatcher(serverConfig.CDP_ASYNC_FUNCTIONS_RUSTY_HOOK_TEAMS, true)
    }

    async execute(
        request: HogFunctionInvocationResult,
        options: AsyncFunctionExecutorOptions = { sync: false }
    ): Promise<HogFunctionInvocationAsyncResponse | undefined> {
        if (!request.asyncFunctionRequest) {
            throw new Error('No async function request provided')
        }

        const loggingContext = {
            hogFunctionId: request.hogFunctionId,
            invocationId: request.id,
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
        request: HogFunctionInvocationResult,
        options?: AsyncFunctionExecutorOptions
    ): Promise<HogFunctionInvocationAsyncResponse | undefined> {
        if (!request.asyncFunctionRequest) {
            return
        }

        const asyncFunctionResponse: HogFunctionInvocationAsyncResponse['asyncFunctionResponse'] = {
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

            // If the caller hasn't forced it to be synchronous and the team has the rustyhook enabled, enqueue it
            if (!options?.sync && this.hogHookEnabledForTeams(request.teamId)) {
                const enqueued = await this.rustyHook.enqueueForHog(request)
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

            asyncFunctionResponse.timings.push({
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
            ...request,
            asyncFunctionResponse,
        }

        return response
    }
}
