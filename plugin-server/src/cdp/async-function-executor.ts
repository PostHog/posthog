import { convertHogToJS } from '@posthog/hogvm'
import { Webhook } from '@posthog/plugin-scaffold'

import { KAFKA_CDP_FUNCTION_CALLBACKS } from '../config/kafka-topics'
import { PluginsServerConfig } from '../types'
import { KafkaProducerWrapper } from '../utils/db/kafka-producer-wrapper'
import { trackedFetch } from '../utils/fetch'
import { status } from '../utils/status'
import { RustyHook } from '../worker/rusty-hook'
import { HogFunctionInvocationAsyncRequest, HogFunctionInvocationAsyncResponse } from './types'

export class AsyncFunctionExecutor {
    constructor(
        private serverConfig: PluginsServerConfig,
        private rustyHook: RustyHook,
        private kafkaProducer: KafkaProducerWrapper
    ) {}

    async execute(request: HogFunctionInvocationAsyncRequest): Promise<HogFunctionInvocationAsyncRequest> {
        const loggingContext = {
            hogFunctionId: request.hogFunctionId,
            invocationId: request.id,
            asyncFunctionName: request.asyncFunctionName,
        }
        status.info('🦔', `[AsyncFunctionExecutor] Executing async function`, loggingContext)

        switch (request.asyncFunctionName) {
            case 'fetch':
                await this.asyncFunctionFetch(request)
                break
            default:
                status.error('🦔', `[HogExecutor] Unknown async function: ${request.asyncFunctionName}`, loggingContext)
        }

        return request
    }

    private async asyncFunctionFetch(request: HogFunctionInvocationAsyncRequest): Promise<any> {
        // TODO: validate the args
        const args = (request.asyncFunctionArgs ?? []).map((arg) => convertHogToJS(arg))
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

                const maybeJson = await fetchResponse.json().catch(() => null)

                response.vmResponse = {
                    status: fetchResponse.status,
                    body: await fetchResponse.text(),
                    json: maybeJson,
                }
            } catch (err) {
                response.error = 'Something went wrong with the fetch request.'
            }

            // NOTE: This feels like overkill but is basically simulating rusty hook's callback that will eventually be implemented
            await this.kafkaProducer!.produce({
                topic: KAFKA_CDP_FUNCTION_CALLBACKS,
                value: Buffer.from(JSON.stringify(response)),
                key: response.id,
                waitForAck: true,
            })
        }
    }
}
