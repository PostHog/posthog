import { Webhook } from '@posthog/plugin-scaffold'

import { KAFKA_CDP_FUNCTION_CALLBACKS } from '../config/kafka-topics'
import { PluginsServerConfig } from '../types'
import { trackedFetch } from '../utils/fetch'
import { status } from '../utils/status'
import { RustyHook } from '../worker/rusty-hook'
import {
    HogFunctionInvocationAsyncRequest,
    HogFunctionInvocationAsyncResponse,
    HogFunctionMessageToQueue,
} from './types'

export class AsyncFunctionExecutor {
    constructor(private serverConfig: PluginsServerConfig, private rustyHook: RustyHook) {}

    async execute(request: HogFunctionInvocationAsyncRequest): Promise<HogFunctionMessageToQueue | undefined> {
        const loggingContext = {
            hogFunctionId: request.hogFunctionId,
            invocationId: request.id,
            asyncFunctionName: request.asyncFunctionName,
        }
        status.info('🦔', `[AsyncFunctionExecutor] Executing async function`, loggingContext)

        switch (request.asyncFunctionName) {
            case 'fetch':
                return await this.asyncFunctionFetch(request)
            default:
                status.error('🦔', `[HogExecutor] Unknown async function: ${request.asyncFunctionName}`, loggingContext)
        }
    }

    private async asyncFunctionFetch(
        request: HogFunctionInvocationAsyncRequest
    ): Promise<HogFunctionMessageToQueue | undefined> {
        // TODO: validate the args
        const args = request.asyncFunctionArgs ?? []
        const url: string = args[0]
        const options = args[1]

        const method = options.method || 'POST'
        const headers = options.headers || {
            'Content-Type': 'application/json',
        }
        const body = options.body || {}

        const webhook: Webhook = {
            url,
            method: method,
            headers: headers,
            body: typeof body === 'string' ? body : JSON.stringify(body, undefined, 4),
        }

        // NOTE: Purposefully disabled for now - once we have callback support we can re-enable
        // const SPECIAL_CONFIG_ID = -3 // Hardcoded to mean Hog
        // const success = await this.rustyHook.enqueueIfEnabledForTeam({
        //     webhook: webhook,
        //     teamId: hogFunction.team_id,
        //     pluginId: SPECIAL_CONFIG_ID,
        //     pluginConfigId: SPECIAL_CONFIG_ID,
        // })

        const success = false

        // TODO: Temporary test code
        if (!success) {
            status.info('🦔', `[HogExecutor] Webhook not sent via rustyhook, sending directly instead`)
            const response: HogFunctionInvocationAsyncResponse = {
                ...request,
            }

            try {
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
                    body
                }

                response.vmResponse = {
                    status: fetchResponse.status,
                    body: body,
                }
            } catch (err) {
                status.error('🦔', `[HogExecutor] Error during fetch`, { ...request, error: String(err) })
                response.error = 'Something went wrong with the fetch request.'
            }

            return {
                topic: KAFKA_CDP_FUNCTION_CALLBACKS,
                value: response,
                key: response.id,
            }
        }
    }
}
