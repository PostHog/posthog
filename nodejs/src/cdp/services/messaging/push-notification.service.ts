import { createSign } from 'crypto'
import { Counter } from 'prom-client'

import {
    CyclotronInvocationQueueParametersSendPushNotificationType,
    PushNotificationPayloadType,
} from '~/cdp/schema/cyclotron'
import { RedisV2 } from '~/common/redis/redis-v2'
import { instrumented } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { FetchOptions, FetchResponse } from '~/common/utils/request'

import type { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, IntegrationType } from '../../types'
import { createAddLogFunction } from '../../utils'
import { EncryptedFields } from '../../utils/encryption-utils'
import { createInvocationResult } from '../../utils/invocation-utils'
import { getDevicePushSubscriptionToken } from '../../utils/push-subscription-utils'
import { IntegrationManagerService } from '../managers/integration-manager.service'

const pushNotificationSentCounter = new Counter({
    name: 'push_notification_sent_total',
    help: 'Total number of push notifications successfully sent',
    labelNames: ['platform'],
})

// Apple rate-limits new APNs provider tokens (returns 429 TooManyProviderTokenUpdates if refreshed more
// than once every ~20 min per key) and accepts a token for up to 1 hour. Cache the signed JWT in Redis
// keyed by the auth key id so the whole fleet reuses one token per key rather than minting one per send.
const APNS_JWT_CACHE_PREFIX = '@posthog/apns-provider-jwt/'
const APNS_JWT_TTL_SECONDS = 45 * 60

export type PushNotificationFetchUtils = {
    trackedFetch: (args: { url: string; fetchParams: FetchOptions; templateId: string }) => Promise<{
        fetchError: Error | null
        fetchResponse: FetchResponse | null
        fetchDuration: number
    }>
    maxFetchTimeoutMs: number
}

export class PushNotificationService {
    constructor(
        private integrationManager: IntegrationManagerService,
        private encryptedFields: EncryptedFields,
        private fetchUtils: PushNotificationFetchUtils,
        private redis: RedisV2 | null
    ) {}

    @instrumented('push-notification.executeSendPushNotification')
    async executeSendPushNotification(
        invocation: CyclotronJobInvocationHogFunction
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        if (invocation.queueParameters?.type !== 'sendPushNotification') {
            throw new Error('Bad invocation')
        }

        const params = invocation.queueParameters as CyclotronInvocationQueueParametersSendPushNotificationType
        const result = createInvocationResult<CyclotronJobInvocationHogFunction>(invocation, {}, { finished: true })
        const addLog = createAddLogFunction(result.logs)

        const pushMetric = (metricName: 'push_sent' | 'push_skipped' | 'push_failed'): void => {
            result.metrics.push({
                team_id: invocation.teamId,
                app_source_id: invocation.parentRunId ?? invocation.functionId,
                instance_id: invocation.state.actionId || invocation.id,
                metric_kind: 'other',
                metric_name: metricName,
                count: 1,
            })
        }

        // Fan out to every selected channel here rather than looping sendPushNotification in the hog
        // template — a hog function only runs one async call per invocation, so a per-channel loop in
        // hog would only ever deliver to the first channel. Each channel is isolated: one failing must
        // not abort the others.
        let errorCount = 0
        let successCount = 0
        let firstError: string | undefined
        for (const integrationId of params.integrationIds) {
            try {
                const integration = await this.integrationManager.get(integrationId)
                if (!integration || integration.team_id !== invocation.teamId) {
                    throw new Error('Push notification integration not found')
                }

                let sent: boolean
                if (integration.kind === 'firebase') {
                    sent = await this.executeFcm(result, params, integration, invocation)
                } else if (integration.kind === 'apns') {
                    sent = await this.executeApns(result, params, integration, invocation)
                } else {
                    throw new Error(`Unsupported push integration kind: ${integration.kind}`)
                }

                if (sent) {
                    successCount++
                    pushMetric('push_sent')
                } else {
                    // A channel with no registered device token for this recipient is skipped, not failed.
                    pushMetric('push_skipped')
                }
            } catch (error) {
                errorCount++
                firstError = firstError ?? error.message
                addLog('error', error.message)
                pushMetric('push_failed')
            }
        }

        // Retry (by surfacing an error) only when a channel was attempted and failed and nothing was
        // delivered. A skip (no device token) is not a delivery, so retrying is safe; but once any
        // channel has delivered we must not retry, or it would re-deliver to that channel.
        const success = successCount > 0 || errorCount === 0
        if (!success) {
            result.error = firstError
        }
        // Surface the error to the hog template too, otherwise its failure message renders blank.
        result.invocation.state.vmState!.stack.push({ success, error: success ? null : (firstError ?? null) })

        return result
    }

    /** Returns true if a notification was handed off to FCM, false if skipped (no device token). */
    private async executeFcm(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
        params: CyclotronInvocationQueueParametersSendPushNotificationType,
        integration: IntegrationType,
        invocation: CyclotronJobInvocationHogFunction
    ): Promise<boolean> {
        const addLog = createAddLogFunction(result.logs)
        const payload = params.payload

        const projectId = integration.config.project_id
        const accessToken = integration.sensitive_config.access_token
        if (!projectId || !accessToken) {
            throw new Error('Firebase integration is missing project_id or access_token')
        }

        const personProperties = invocation.state.globals.person?.properties
        const token = getDevicePushSubscriptionToken(personProperties, projectId, this.encryptedFields)

        if (!token) {
            addLog('warn', `No active FCM device token found for distinct_id: ${params.distinctId}`)
            return false
        }

        const url = `https://fcm.googleapis.com/v1/projects/${projectId}/messages:send`
        const templateId = result.invocation.hogFunction.template_id ?? 'unknown'

        const fcmMessage = this.buildFcmMessage(token, payload)

        const fetchParams: FetchOptions = {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${accessToken}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(fcmMessage),
        }

        if (params.timeoutMs !== undefined) {
            fetchParams.timeoutMs = Math.min(params.timeoutMs, this.fetchUtils.maxFetchTimeoutMs)
        }

        const { fetchError, fetchResponse, fetchDuration } = await this.fetchUtils.trackedFetch({
            url,
            fetchParams,
            templateId,
        })

        result.invocation.state.timings.push({
            kind: 'async_function',
            duration_ms: fetchDuration,
        })

        let body: unknown = undefined
        try {
            body = await fetchResponse?.text()
            if (typeof body === 'string') {
                try {
                    body = parseJSON(body)
                } catch {
                    // Pass through
                }
            }
        } catch (e) {
            addLog('error', `Failed to parse response body: ${e.message}`)
        }

        const status = fetchResponse?.status

        if (!fetchResponse || (status && status >= 400)) {
            addLog(
                'error',
                `FCM send error. Status: ${status ?? '(none)'}. Body: ${typeof body === 'string' ? body : JSON.stringify(body)}. Fetch error: ${fetchError?.message ?? 'none'}`
            )
            throw new Error(
                `Push notification failed with status ${status ?? '(none)'}.${fetchError ? ` Error: ${fetchError.message}.` : ''}`
            )
        }

        pushNotificationSentCounter.labels({ platform: 'fcm' }).inc()
        addLog('info', `Push notification sent via FCM`)
        return true
    }

    /** Returns true if a notification was handed off to APNS, false if skipped (no device token). */
    private async executeApns(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
        params: CyclotronInvocationQueueParametersSendPushNotificationType,
        integration: IntegrationType,
        invocation: CyclotronJobInvocationHogFunction
    ): Promise<boolean> {
        const addLog = createAddLogFunction(result.logs)
        const payload = params.payload

        const signingKey = integration.sensitive_config.signing_key
        const keyId = integration.config.key_id
        const appleTeamId = integration.config.team_id
        const bundleId = integration.config.bundle_id
        if (!signingKey || !keyId || !appleTeamId || !bundleId) {
            throw new Error('APNS integration is missing required fields: signing_key, key_id, team_id, or bundle_id')
        }

        const personProperties = invocation.state.globals.person?.properties
        const token = getDevicePushSubscriptionToken(personProperties, bundleId, this.encryptedFields)

        if (!token) {
            addLog('warn', `No active APNS device token found for distinct_id: ${params.distinctId}`)
            return false
        }

        const jwt = await this.generateApnsJwt(appleTeamId, keyId, signingKey)

        const apnsPayload = this.buildApnsPayload(payload)
        const apnsHost =
            integration.config.environment === 'sandbox' ? 'api.sandbox.push.apple.com' : 'api.push.apple.com'
        const url = `https://${apnsHost}/3/device/${token}`

        const headers: Record<string, string> = {
            Authorization: `bearer ${jwt}`,
            'apns-topic': bundleId,
            'apns-push-type': 'alert',
        }
        if (payload.collapseKey) {
            headers['apns-collapse-id'] = payload.collapseKey
        }
        if (payload.ttlSeconds !== undefined) {
            headers['apns-expiration'] = String(Math.floor(Date.now() / 1000) + payload.ttlSeconds)
        }
        if (payload.apns?.interruptionLevel) {
            headers['apns-priority'] = payload.apns.interruptionLevel === 'passive' ? '5' : '10'
        }

        const fetchParams: FetchOptions = {
            method: 'POST',
            headers,
            body: JSON.stringify(apnsPayload),
            // APNs requires HTTP/2
            allowH2: true,
        }

        if (params.timeoutMs !== undefined) {
            fetchParams.timeoutMs = Math.min(params.timeoutMs, this.fetchUtils.maxFetchTimeoutMs)
        }

        const templateId = result.invocation.hogFunction.template_id ?? 'unknown'

        const { fetchError, fetchResponse, fetchDuration } = await this.fetchUtils.trackedFetch({
            url,
            fetchParams,
            templateId,
        })

        result.invocation.state.timings.push({
            kind: 'async_function',
            duration_ms: fetchDuration,
        })

        let body: unknown = undefined
        try {
            body = await fetchResponse?.text()
            if (typeof body === 'string' && body.length > 0) {
                try {
                    body = parseJSON(body)
                } catch {
                    // Pass through
                }
            }
        } catch (e) {
            addLog('error', `Failed to parse response body: ${e.message}`)
        }

        const status = fetchResponse?.status

        if (!fetchResponse || (status && status >= 400)) {
            const reason =
                body && typeof body === 'object' && 'reason' in body ? ` Reason: ${(body as any).reason}.` : ''
            addLog(
                'error',
                `APNS send error. Status: ${status ?? '(none)'}. Body: ${typeof body === 'string' ? body : JSON.stringify(body)}. Fetch error: ${fetchError?.message ?? 'none'}`
            )
            throw new Error(
                `Push notification failed with status ${status ?? '(none)'}.${reason}${fetchError ? ` Error: ${fetchError.message}.` : ''}`
            )
        }

        pushNotificationSentCounter.labels({ platform: 'apns' }).inc()
        addLog('info', `Push notification sent via APNS`)
        return true
    }

    private async generateApnsJwt(teamId: string, keyId: string, signingKey: string): Promise<string> {
        // Key on the Apple team id + key id, not the key id alone: key ids are unique only within an
        // Apple account, so two PostHog teams could share one. Keying on both preserves fleet-wide reuse
        // per signing key while preventing a cross-account collision that would serve the wrong token.
        const cacheKey = `${APNS_JWT_CACHE_PREFIX}${teamId}/${keyId}`

        const cached = await this.redis?.useClient({ name: 'apns-jwt-read', failOpen: true }, (client) =>
            client.get(cacheKey)
        )
        if (cached) {
            return cached
        }

        const header = Buffer.from(JSON.stringify({ alg: 'ES256', kid: keyId })).toString('base64url')
        const now = Math.floor(Date.now() / 1000)
        const claims = Buffer.from(JSON.stringify({ iss: teamId, iat: now })).toString('base64url')
        const signingInput = `${header}.${claims}`
        const sign = createSign('SHA256')
        sign.update(signingInput)
        const signature = sign.sign({ key: signingKey, dsaEncoding: 'ieee-p1363' }, 'base64url')
        const jwt = `${signingInput}.${signature}`

        await this.redis?.useClient({ name: 'apns-jwt-write', failOpen: true }, (client) =>
            client.set(cacheKey, jwt, 'EX', APNS_JWT_TTL_SECONDS)
        )
        return jwt
    }

    private buildApnsPayload(payload: PushNotificationPayloadType): Record<string, unknown> {
        const alert: Record<string, unknown> = { title: payload.title }
        if (payload.body) {
            alert.body = payload.body
        }
        if (payload.apns?.subtitle) {
            alert.subtitle = payload.apns.subtitle
        }

        const aps: Record<string, unknown> = { alert }

        if (payload.apns) {
            if (payload.apns.sound) {
                aps.sound = payload.apns.sound
            }
            if (payload.apns.badge !== undefined) {
                aps.badge = payload.apns.badge
            }
            if (payload.apns.category) {
                aps.category = payload.apns.category
            }
            if (payload.apns.threadId) {
                aps['thread-id'] = payload.apns.threadId
            }
            if (payload.apns.interruptionLevel) {
                aps['interruption-level'] = payload.apns.interruptionLevel
            }
            if (payload.apns.relevanceScore !== undefined) {
                aps['relevance-score'] = payload.apns.relevanceScore
            }
            if (payload.apns.contentAvailable) {
                aps['content-available'] = 1
            }
            if (payload.apns.mutableContent || payload.image) {
                aps['mutable-content'] = 1
            }
            if (payload.apns.targetContentId) {
                aps['target-content-id'] = payload.apns.targetContentId
            }
        } else if (payload.image) {
            aps['mutable-content'] = 1
        }

        // Spread user data first so the reserved `aps` and `image_url` keys always win — a custom data
        // key named `aps` must not overwrite the notification payload.
        const result: Record<string, unknown> = { ...(payload.data ?? {}), aps }

        if (payload.image) {
            result['image_url'] = payload.image
        }

        return result
    }

    private buildFcmMessage(token: string, payload: PushNotificationPayloadType): Record<string, unknown> {
        const notification: Record<string, string> = { title: payload.title }
        if (payload.body) {
            notification.body = payload.body
        }
        if (payload.image) {
            notification.image = payload.image
        }

        const message: Record<string, unknown> = {
            token,
            notification,
        }

        if (payload.data) {
            message.data = payload.data
        }

        // Android-specific config
        if (payload.android || payload.collapseKey || payload.ttlSeconds !== undefined) {
            const android: Record<string, unknown> = {}
            if (payload.collapseKey) {
                android.collapse_key = payload.collapseKey
            }
            if (payload.ttlSeconds !== undefined) {
                android.ttl = `${payload.ttlSeconds}s`
            }
            if (payload.android) {
                if (payload.android.priority) {
                    android.priority = payload.android.priority.toUpperCase()
                }
                const androidNotification: Record<string, string> = {}
                if (payload.android.channelId) {
                    androidNotification.channel_id = payload.android.channelId
                }
                if (payload.android.sound) {
                    androidNotification.sound = payload.android.sound
                }
                if (payload.android.tag) {
                    androidNotification.tag = payload.android.tag
                }
                if (payload.android.icon) {
                    androidNotification.icon = payload.android.icon
                }
                if (payload.android.color) {
                    androidNotification.color = payload.android.color
                }
                if (payload.android.clickAction) {
                    androidNotification.click_action = payload.android.clickAction
                }
                if (Object.keys(androidNotification).length > 0) {
                    android.notification = androidNotification
                }
            }
            message.android = android
        }

        // APNS overrides (for iOS devices via FCM)
        if (payload.apns) {
            const aps: Record<string, unknown> = {}
            if (payload.apns.sound) {
                aps.sound = payload.apns.sound
            }
            if (payload.apns.badge !== undefined) {
                aps.badge = payload.apns.badge
            }
            if (payload.apns.category) {
                aps.category = payload.apns.category
            }
            if (payload.apns.threadId) {
                aps['thread-id'] = payload.apns.threadId
            }
            if (payload.apns.interruptionLevel) {
                aps['interruption-level'] = payload.apns.interruptionLevel
            }
            if (payload.apns.relevanceScore !== undefined) {
                aps['relevance-score'] = payload.apns.relevanceScore
            }
            if (payload.apns.subtitle) {
                // Subtitle goes in the alert object
                notification.subtitle = payload.apns.subtitle
            }
            if (payload.apns.mutableContent) {
                aps['mutable-content'] = 1
            }
            if (payload.apns.targetContentId) {
                aps['target-content-id'] = payload.apns.targetContentId
            }

            message.apns = {
                payload: { aps },
            }

            // Set collapse ID via APNS header if collapseKey is set
            if (payload.collapseKey) {
                ;(message.apns as Record<string, unknown>).headers = {
                    'apns-collapse-id': payload.collapseKey,
                }
            }
            if (payload.ttlSeconds !== undefined) {
                const headers = ((message.apns as Record<string, unknown>).headers as Record<string, string>) ?? {}
                headers['apns-expiration'] = String(Math.floor(Date.now() / 1000) + payload.ttlSeconds)
                ;(message.apns as Record<string, unknown>).headers = headers
            }
        }

        return { message }
    }
}
