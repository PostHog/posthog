import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { instrumented } from '~/common/tracing/tracing-utils'
import { ACCESS_TOKEN_PLACEHOLDER } from '~/config/constants'
import { FetchOptions, FetchResponse } from '~/utils/request'

import { Hub } from '../../../types'
import { parseJSON } from '../../../utils/json-parse'
import { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult } from '../../types'
import { createAddLogFunction } from '../../utils'
import { createInvocationResult } from '../../utils/invocation-utils'
import { HogInputsService } from '../hog-inputs.service'
import { FcmErrorDetail, PushSubscriptionsManagerService } from '../managers/push-subscriptions-manager.service'

export type FcmTokenFromInvocationArgs = {
    inputs: Record<string, unknown> | undefined
    inputsSchema: { type: string; key: string }[] | undefined
}

const pushNotificationSentCounter = new Counter({
    name: 'push_notification_sent_total',
    help: 'Total number of push notifications successfully sent',
    labelNames: ['platform'],
})

export type PushNotificationFetchUtils = {
    trackedFetch: (args: { url: string; fetchParams: FetchOptions; templateId: string }) => Promise<{
        fetchError: Error | null
        fetchResponse: FetchResponse | null
        fetchDuration: number
    }>
    isFetchResponseRetriable: (response: FetchResponse | null, error: any) => boolean
    maxFetchTimeoutMs: number
}

export type PushNotificationServiceHub = Pick<
    Hub,
    'CDP_FETCH_RETRIES' | 'CDP_FETCH_BACKOFF_BASE_MS' | 'CDP_FETCH_BACKOFF_MAX_MS'
>

export class PushNotificationService {
    constructor(
        private hub: PushNotificationServiceHub,
        private hogInputsService: HogInputsService,
        private pushSubscriptionsManager: PushSubscriptionsManagerService,
        private fetchUtils: PushNotificationFetchUtils
    ) {}

    getFcmTokenFromInvocation(args: FcmTokenFromInvocationArgs): string | null {
        if (!args.inputs) {
            return null
        }
        const pushSubscriptionKey = args.inputsSchema?.find((schema) => schema.type === 'push_subscription')?.key
        if (!pushSubscriptionKey || !args.inputs[pushSubscriptionKey]) {
            return null
        }
        const value = args.inputs[pushSubscriptionKey]
        return typeof value === 'string' ? value : null
    }

    @instrumented('push-notification.executeSendPushNotification')
    async executeSendPushNotification(
        invocation: CyclotronJobInvocationHogFunction
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        const templateId = invocation.hogFunction.template_id ?? 'unknown'
        if (invocation.queueParameters?.type !== 'sendPushNotification') {
            throw new Error('Bad invocation')
        }

        const params = invocation.queueParameters
        const result = createInvocationResult<CyclotronJobInvocationHogFunction>(invocation, {}, { finished: false })
        const addLog = createAddLogFunction(result.logs)

        const method = params.method.toUpperCase()
        let headers = params.headers ?? {}

        const integrationInputs = await this.hogInputsService.loadIntegrationInputs(invocation.hogFunction)
        if (Object.keys(integrationInputs).length > 0) {
            for (const [key, value] of Object.entries(integrationInputs)) {
                const accessToken: string = value.value?.access_token_raw
                if (!accessToken) {
                    continue
                }
                const placeholder: string = ACCESS_TOKEN_PLACEHOLDER + invocation.hogFunction.inputs?.[key]?.value

                if (placeholder && accessToken) {
                    const replace = (val: string) => val.replaceAll(placeholder, accessToken)
                    params.body = params.body ? replace(params.body) : params.body
                    headers = Object.fromEntries(
                        Object.entries(params.headers ?? {}).map(([k, v]) => [
                            k,
                            typeof v === 'string' ? replace(v) : v,
                        ])
                    )
                    params.url = replace(params.url)
                }
            }
        }

        const fetchParams: FetchOptions = { method, headers }
        if (!['GET', 'HEAD'].includes(method) && params.body) {
            fetchParams.body = params.body
        }
        if (params.timeoutMs !== undefined) {
            fetchParams.timeoutMs = Math.min(params.timeoutMs, this.fetchUtils.maxFetchTimeoutMs)
        }

        const { fetchError, fetchResponse, fetchDuration } = await this.fetchUtils.trackedFetch({
            url: params.url,
            fetchParams,
            templateId,
        })

        result.invocation.state.timings.push({
            kind: 'async_function',
            duration_ms: fetchDuration,
        })
        result.invocation.state.attempts++

        if (!fetchResponse || (fetchResponse?.status && fetchResponse.status >= 400)) {
            const backoffMs = Math.min(
                this.hub.CDP_FETCH_BACKOFF_BASE_MS * result.invocation.state.attempts +
                    Math.floor(Math.random() * this.hub.CDP_FETCH_BACKOFF_BASE_MS),
                this.hub.CDP_FETCH_BACKOFF_MAX_MS
            )
            const canRetry = this.fetchUtils.isFetchResponseRetriable(fetchResponse, fetchError)
            let message = `Push notification request failed on attempt ${result.invocation.state.attempts} with status code ${
                fetchResponse?.status ?? '(none)'
            }.`
            if (fetchError) {
                message += ` Error: ${fetchError.message}.`
            }
            if (canRetry) {
                message += ` Retrying in ${backoffMs}ms.`
            }
            addLog('error', message)
            if (canRetry && result.invocation.state.attempts < this.hub.CDP_FETCH_RETRIES) {
                await fetchResponse?.dump()
                result.invocation.queue = 'hog'
                result.invocation.queueParameters = { ...params }
                result.invocation.queuePriority = invocation.queuePriority + 1
                result.invocation.queueScheduledAt = DateTime.utc().plus({ milliseconds: backoffMs })
                return result
            }
            result.error = new Error(message)
        }

        result.invocation.state.attempts = 0

        let body: unknown = undefined
        try {
            body = await fetchResponse?.text()
            if (typeof body === 'string') {
                try {
                    body = parseJSON(body)
                } catch (e) {
                    // Pass through
                }
            }
        } catch (e) {
            addLog('error', `Failed to parse response body: ${e.message}`)
            body = undefined
        }

        const fcmToken = this.getFcmTokenFromInvocation({
            inputs: invocation.state.globals?.inputs,
            inputsSchema: invocation.hogFunction.inputs_schema,
        })
        if (fcmToken) {
            const status = fetchResponse?.status
            let errorDetails: FcmErrorDetail[] | undefined
            if (status === 400 && body && typeof body === 'object') {
                const errorBody = body as Record<string, unknown>
                const error = errorBody?.error as { details?: FcmErrorDetail[] } | undefined
                errorDetails = error?.details
            }
            await this.pushSubscriptionsManager.updateTokenLifecycle(invocation.teamId, fcmToken, status, errorDetails)
            if (status && status >= 200 && status < 300) {
                pushNotificationSentCounter.labels({ platform: 'android' }).inc()
            }
        } else {
            addLog('warn', 'FCM token not found in inputs, skipping FCM response handling')
        }

        const hogVmResponse: { status: number; body: unknown } = {
            status: fetchResponse?.status ?? 500,
            body,
        }
        result.invocation.state.vmState!.stack.push(hogVmResponse)
        result.execResult = hogVmResponse
        result.metrics.push({
            team_id: invocation.teamId,
            app_source_id: invocation.functionId,
            metric_kind: 'other',
            metric_name: 'sendPushNotification' as const,
            count: 1,
        })
        return result
    }
}
