import { Webhook } from '@posthog/plugin-scaffold'

import { PluginsServerConfig } from '../types'
import { trackedFetch } from '../utils/fetch'
import { status } from '../utils/status'
import { RustyHook } from '../worker/rusty-hook'
import { HogFunctionInvocationAsyncResponse, HogFunctionInvocationResult } from './types'

export type AsyncFunctionExecutorOptions = {
    sync?: boolean
}

export class AsyncFunctionExecutor {
    constructor(private serverConfig: PluginsServerConfig, private rustyHook: RustyHook) {}

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
        // TODO: validate the args
        // TODO: figure out `options`
        const forceUseRustyHookForTesting = true
        if (!options?.sync === false || forceUseRustyHookForTesting) {
            // TODO: This is a hack because it's surprising to me that the body is currently an
            // embedded JS(ON) object and not a string. We could handle this on the Hog side instead
            // if desired.
            const args = request.asyncFunctionRequest?.args[1]
            let body = args.body
            if (body) {
                body = typeof body === 'string' ? body : JSON.stringify(body, undefined, 4)
                request.asyncFunctionRequest!.args[1].body = body
            }

            await this.rustyHook.enqueueForHog(request)
            return
        }

        status.info('🦔', `[HogExecutor] Webhook not sent via rustyhook, sending directly instead`)

        const args = request.asyncFunctionRequest!.args ?? []
        const url: string = args[0]
        const fetchOptions = args[1]

        const method = fetchOptions.method || 'POST'
        const headers = fetchOptions.headers || {
            'Content-Type': 'application/json',
        }
        const body = fetchOptions.body || {}

        const webhook: Webhook = {
            url,
            method: method,
            headers: headers,
            body: typeof body === 'string' ? body : JSON.stringify(body, undefined, 4),
        }

        const asyncFunctionResponse: HogFunctionInvocationAsyncResponse['asyncFunctionResponse'] = {
            timings: [],
        }

        try {
            const start = performance.now()
            const fetchResponse = await trackedFetch(url, {
                method: webhook.method,
                body: webhook.body,
                headers: webhook.headers,
                timeout: this.serverConfig.EXTERNAL_REQUEST_TIMEOUT_MS,
            })

            let body = await fetchResponse.text()
            try {
                body = JSON.parse(body)
            } catch (err) {
                // Ignore
            }

            const duration = performance.now() - start

            asyncFunctionResponse.timings.push({
                kind: 'async_function',
                duration_ms: duration,
            })

            asyncFunctionResponse.vmResponse = {
                status: fetchResponse.status,
                body: body,
            }
        } catch (err) {
            status.error('🦔', `[HogExecutor] Error during fetch`, { ...request, error: String(err) })
            asyncFunctionResponse.error = 'Something went wrong with the fetch request.'
        }

        const response: HogFunctionInvocationAsyncResponse = {
            ...request,
            asyncFunctionResponse,
        }

        return response
    }
}
