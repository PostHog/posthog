import { createHash, createSign } from 'crypto'
import { DateTime } from 'luxon'
import { Counter, Histogram } from 'prom-client'

import {
    CyclotronInvocationQueueParametersSendPushNotificationType,
    PushNotificationPayloadType,
} from '~/cdp/schema/cyclotron'
import { RedisV2 } from '~/common/redis/redis-v2'
import { instrumented } from '~/common/tracing/tracing-utils'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'
import { FetchOptions, FetchResponse } from '~/common/utils/request'

import type { CyclotronJobInvocationHogFunction, CyclotronJobInvocationResult, IntegrationType } from '../../types'
import { createAddLogFunction } from '../../utils'
import { EncryptedFields } from '../../utils/encryption-utils'
import { createInvocationResult } from '../../utils/invocation-utils'
import { getDevicePushSubscriptionToken } from '../../utils/push-subscription-utils'
import { IntegrationManagerService } from '../managers/integration-manager.service'
import { MessageAssetsService } from './message-assets.service'
import {
    NormalizedPushError,
    PushPlatform,
    PushSendError,
    normalizeApnsError,
    normalizeFcmError,
} from './push-notification-errors'

const pushNotificationSentCounter = new Counter({
    name: 'push_notification_sent_total',
    help: 'Total number of push notifications successfully sent',
    labelNames: ['platform'],
})

const pushNotificationTokenPrunedCounter = new Counter({
    name: 'push_notification_token_pruned_total',
    help: 'Total number of device tokens removed after the provider reported them no longer registered',
    labelNames: ['platform'],
})

const pushNotificationFailedCounter = new Counter({
    name: 'push_notification_failed_total',
    help: 'Push notifications that failed to send, by platform and normalized failure reason.',
    labelNames: ['platform', 'reason'],
})

const pushNotificationSkippedCounter = new Counter({
    name: 'push_notification_skipped_total',
    help: 'Push sends not delivered without an outright failure, by platform and reason. no_token = the recipient never registered a device; unregistered = the provider reported the token dead and it was removed.',
    labelNames: ['platform', 'reason'],
})

const pushNotificationSendDurationMs = new Histogram({
    name: 'push_notification_send_duration_ms',
    help: 'Duration of a push send request to the provider, by platform.',
    labelNames: ['platform'],
    buckets: [10, 25, 50, 100, 200, 500, 1000, 2000, 5000, 10000],
})

const pushNotificationRescheduledCounter = new Counter({
    name: 'push_notification_rescheduled_total',
    help: 'Push sends rescheduled after a transient provider failure (throttle / 5xx / network) instead of being dropped. A sustained rate for one platform means that provider is rate-limiting the sending project.',
    labelNames: ['platform'],
})

// Apple rate-limits new APNs provider tokens (returns 429 TooManyProviderTokenUpdates if refreshed more
// than once every ~20 min per key) and accepts a token for up to 1 hour. Cache the signed JWT in Valkey
// keyed by the auth key id so the whole fleet reuses one token per key rather than minting one per send.
const APNS_JWT_CACHE_PREFIX = '@posthog/apns-provider-jwt/'
const APNS_JWT_TTL_SECONDS = 45 * 60

// One entry per signing key, so the ceiling is the number of APNs integrations routed through this pod.
// Pruned on write rather than on a timer.
const APNS_JWT_LOCAL_CACHE_MAX = 500

// A push action fans out to its selected channels within one invocation. Cap the count so a workflow
// crafted with a huge channel list can't tie up a worker with an unbounded outbound-request loop; a real
// push targets a handful of provider integrations, not thousands.
const MAX_PUSH_CHANNELS = 10

// Cap a provider-supplied Retry-After. FCM returns one on QUOTA_EXCEEDED and honoring it is the point,
// but a hostile or misconfigured value must not park an invocation for hours.
const MAX_RETRY_AFTER_MS = 5 * 60 * 1000

function stringifyBody(body: unknown): string {
    return typeof body === 'string' ? body : JSON.stringify(body)
}

// Retry-After is delta-seconds or an HTTP-date. Return a bounded millisecond delay, or undefined if the
// header is absent or unparseable so the caller falls back to exponential backoff.
function parseRetryAfterMs(response: FetchResponse | null): number | undefined {
    const header = response?.headers?.['retry-after']
    if (!header) {
        return undefined
    }
    const seconds = Number(header)
    const ms = Number.isFinite(seconds) ? seconds * 1000 : Date.parse(header) - Date.now()
    if (!Number.isFinite(ms) || ms <= 0) {
        return undefined
    }
    return Math.min(ms, MAX_RETRY_AFTER_MS)
}

// Exponential-ish backoff with jitter for a retry when the provider didn't give a Retry-After.
function backoffAt(baseMs: number, maxMs: number, tries: number): DateTime {
    const delay = Math.min(baseMs * tries + Math.floor(Math.random() * baseMs), maxMs)
    return DateTime.utc().plus({ milliseconds: delay })
}

// Correlation ids stamped into every notification's data payload. An open happens on the device, so the
// SDK is the only thing that can observe it; these ride along in the payload and come back on the
// captured open event, which is what lets an open be attributed to the workflow and step that sent it.
// Without them an open is only ever a global count.
//
// The key and the shape are fixed by the mobile SDKs: both read the single `posthog` entry out of the
// notification payload and re-emit each of its keys as `$notification_<key>` on `$push_notification_opened`.
// Nothing outside that entry is read, so these ids have to be nested under it rather than sent as
// sibling keys.
const PUSH_CORRELATION_KEY = 'posthog'

// Serialized rather than nested as an object because FCM's `data` map only accepts string values. Both
// SDKs parse this entry from either a dictionary or a JSON string, on either delivery route, so one
// encoding covers FCM and direct APNs.
function pushCorrelationData(invocation: CyclotronJobInvocationHogFunction): Record<string, string> {
    const correlation: Record<string, string> = {
        workflow_id: invocation.functionId,
        invocation_id: invocation.id,
    }
    // Absent for a push sent outside a workflow step, where there is no step to attribute an open to.
    if (invocation.state.actionId) {
        correlation.action_id = invocation.state.actionId
    }
    // Send metrics are attributed to `parentRunId ?? functionId`, so a batch run counts its sends
    // against the batch job rather than the workflow. An open has to be attributable the same way or
    // the two don't divide into a rate — which is why the email tracking code carries this id too.
    if (invocation.parentRunId) {
        correlation.parent_run_id = invocation.parentRunId
    }
    return { [PUSH_CORRELATION_KEY]: JSON.stringify(correlation) }
}

function pushSendError(platform: PushPlatform, err: NormalizedPushError, retryAfterMs?: number): PushSendError {
    // Append the raw provider code so the failure surfaced to the hog template stays debuggable, while
    // the human-readable sentence leads.
    const message = err.code ? `${err.message} [${err.code}]` : err.message
    return new PushSendError(message, platform, err.reason, err.level, err.retriable, err.code, retryAfterMs)
}

export type PushNotificationFetchUtils = {
    trackedFetch: (args: { url: string; fetchParams: FetchOptions; templateId: string }) => Promise<{
        fetchError: Error | null
        fetchResponse: FetchResponse | null
        fetchDuration: number
    }>
    maxFetchTimeoutMs: number
    // Retry budget + backoff for transient provider failures, wired from CDP_FETCH_* so push shares the
    // same policy as the generic fetch destinations.
    maxRetries: number
    backoffBaseMs: number
    backoffMaxMs: number
}

export class PushNotificationService {
    constructor(
        private integrationManager: IntegrationManagerService,
        private encryptedFields: EncryptedFields,
        private fetchUtils: PushNotificationFetchUtils,
        private valkey: RedisV2,
        private messageAssetsService?: MessageAssetsService
    ) {}

    // Both Valkey calls for the APNs token are failOpen, so an outage turns every send into a fresh mint —
    // the exact pattern Apple answers with 429 TooManyProviderTokenUpdates. This per-pod copy bounds that
    // to one token per pod per TTL. It is a fallback, not the cache: Valkey is still read first, so the
    // fleet normally shares one token per key.
    private apnsJwtLocalCache = new Map<string, { jwt: string; expiresAtMs: number }>()

    @instrumented('push-notification.executeSendPushNotification')
    async executeSendPushNotification(
        invocation: CyclotronJobInvocationHogFunction,
        isTest = false
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        if (invocation.queueParameters?.type !== 'sendPushNotification') {
            throw new Error('Bad invocation')
        }

        const queueParams = invocation.queueParameters as CyclotronInvocationQueueParametersSendPushNotificationType
        // Stamp the correlation ids last so they win over any custom `data` key of the same name. The
        // enriched copy is local: `invocation.queueParameters` stays untouched, so a reschedule re-derives
        // these rather than persisting them onto the job.
        const params: CyclotronInvocationQueueParametersSendPushNotificationType = {
            ...queueParams,
            payload: {
                ...queueParams.payload,
                data: { ...(queueParams.payload?.data ?? {}), ...pushCorrelationData(invocation) },
            },
        }
        const result = createInvocationResult<CyclotronJobInvocationHogFunction>(invocation, {}, { finished: true })
        const addLog = createAddLogFunction(result.logs)

        // How many times this send has already been rescheduled after a transient failure, carried on the
        // invocation's queue metadata across reschedules.
        const metadata = (invocation.queueMetadata as { tries?: number }) || {}
        const tries = metadata.tries ?? 0

        // Business metrics are emitted once, at the terminal outcome below, rather than per channel — a
        // rescheduled attempt must not re-count the same notification's skips or failures on every retry.
        const pushMetric = (metricName: 'push_sent' | 'push_skipped' | 'push_failed', count: number): void => {
            // A test send from the editor's "Run test" must not land in the workflow's Metrics tab,
            // matching what the email path already does.
            if (count <= 0 || isTest) {
                return
            }
            result.metrics.push({
                team_id: invocation.teamId,
                app_source_id: invocation.parentRunId ?? invocation.functionId,
                instance_id: invocation.state.actionId || invocation.id,
                metric_kind: 'push',
                metric_name: metricName,
                count,
            })
        }

        // Fan out to every selected channel here rather than looping sendPushNotification in the hog
        // template — a hog function only runs one async call per invocation, so a per-channel loop in
        // hog would only ever deliver to the first channel. Each channel is isolated: one failing must
        // not abort the others.
        // Dedupe so duplicate channel entries can't notify the same device twice, and cap the fan-out so a
        // crafted workflow can't occupy the worker with an unbounded loop.
        const uniqueIntegrationIds = [...new Set(params.integrationIds)]
        const integrationIds = uniqueIntegrationIds.slice(0, MAX_PUSH_CHANNELS)
        if (uniqueIntegrationIds.length > MAX_PUSH_CHANNELS) {
            addLog(
                'warn',
                `Push notification has ${uniqueIntegrationIds.length} channels; only the first ${MAX_PUSH_CHANNELS} will be delivered.`
            )
        }

        let successCount = 0
        let skippedCount = 0
        let otherErrorCount = 0
        const errors: PushSendError[] = []
        let firstError: string | undefined
        // Which providers took delivery. Only its emptiness is read, to decide whether there is a
        // delivered notification worth capturing.
        const deliveredPlatforms = new Set<string>()
        for (const integrationId of integrationIds) {
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
                    deliveredPlatforms.add(integration.kind === 'firebase' ? 'Firebase' : 'APNs')
                } else {
                    // A channel with no registered device token for this recipient is skipped, not failed.
                    skippedCount++
                }
            } catch (error) {
                firstError = firstError ?? error.message
                if (error instanceof PushSendError) {
                    // Normalized provider failure: log once at the reason's severity. The failure metric is
                    // emitted at the terminal outcome below, so a rescheduled retry doesn't over-count it.
                    errors.push(error)
                    addLog(error.level, error.message)
                } else {
                    otherErrorCount++
                    addLog('error', error.message)
                }
            }
        }

        const errorCount = errors.length + otherErrorCount
        const success = successCount > 0 || errorCount === 0
        const retriableErrors = errors.filter((e) => e.retriable)

        // Nothing delivered and a channel failed transiently: reschedule the whole invocation instead of
        // dropping the notification. Only safe when nothing was delivered — once a channel has sent,
        // retrying would re-deliver to it. A terminally-failed channel (e.g. a 400) sitting alongside a
        // transient one is re-attempted on each retry; that's acceptable, it just re-fails, bounded by the
        // budget. `tries` starts at 0, so this allows CDP_FETCH_RETRIES reschedules after the first attempt
        // (the notification is tried maxRetries + 1 times in total).
        if (!success && retriableErrors.length > 0 && tries < this.fetchUtils.maxRetries) {
            const nextTries = tries + 1
            // Restore queueParameters — createInvocationResult cleared them. Without this the retry dequeue
            // routes on an undefined queue type and resumes the hog VM instead of re-running this send,
            // which pops an empty stack and throws a bytecode error, dropping the notification.
            result.invocation.queueParameters = invocation.queueParameters
            result.invocation.queueMetadata = { ...metadata, tries: nextTries }
            result.invocation.queuePriority = nextTries
            // Retrying re-attempts every failed channel, so wait out the LONGEST Retry-After any channel
            // asked for; fall back to exponential backoff when none provided one.
            const retryAfterValues = retriableErrors
                .map((e) => e.retryAfterMs)
                .filter((ms): ms is number => ms !== undefined)
            result.invocation.queueScheduledAt =
                retryAfterValues.length > 0
                    ? DateTime.utc().plus({ milliseconds: Math.max(...retryAfterValues) })
                    : backoffAt(this.fetchUtils.backoffBaseMs, this.fetchUtils.backoffMaxMs, nextTries)
            result.finished = false
            // Count each distinct throttled platform so the metric shows which provider is rate-limiting.
            for (const platform of new Set(retriableErrors.map((e) => e.platform))) {
                pushNotificationRescheduledCounter.labels({ platform }).inc()
            }
            addLog(
                'warn',
                `Push notification throttled or temporarily unavailable; retrying (attempt ${nextTries}/${this.fetchUtils.maxRetries}).`
            )
            // No business metric or VM-state push here — the eventual terminal attempt reports the outcome.
            return result
        }

        // Terminal outcome: emit the per-notification business metrics once, and label the ops failure
        // metric by platform + reason for every channel that failed for good.
        pushMetric('push_sent', successCount)
        pushMetric('push_skipped', skippedCount)
        pushMetric('push_failed', errorCount)

        // Captured at the terminal outcome for the same reason the business metrics are: a rescheduled
        // attempt returns earlier, so a retried notification produces one asset rather than one per try.
        // Only a delivered notification is captured, matching email: an asset is a snapshot of what a
        // recipient received, and a skip has no recipient. Skips stay visible as `push_skipped` plus the
        // per-channel run log explaining why.
        // Skipped for a test send for the same reason the metrics are: the Assets tab should show
        // what real recipients were sent, not what an editor preview produced.
        if (this.messageAssetsService && successCount > 0 && !isTest) {
            // Best-effort: the notification is already delivered by this point, so a capture failure
            // must not fail the invocation. Throwing here would send the whole batch back for a retry
            // and deliver every notification in it a second time. Losing an Assets row is the cheaper
            // outcome, and it is the same trade the flush path already makes on a Kafka failure.
            try {
                const assetRow = this.messageAssetsService.buildRowForPush(invocation, params, [...deliveredPlatforms])
                if (assetRow) {
                    result.messageAssets.push(assetRow)
                }
            } catch (err) {
                addLog('warn', 'The notification was delivered but could not be captured for the Assets tab.')
                logger.warn('⚠️', `failed to capture a sent push notification: ${err}`, { error: String(err) })
            }
        }
        for (const error of errors) {
            pushNotificationFailedCounter.labels({ platform: error.platform, reason: error.reason }).inc()
        }
        if (otherErrorCount > 0) {
            pushNotificationFailedCounter.labels({ platform: 'unknown', reason: 'unknown' }).inc(otherErrorCount)
        }
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
            pushNotificationSkippedCounter.labels({ platform: 'fcm', reason: 'no_token' }).inc()
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
        pushNotificationSendDurationMs.labels({ platform: 'fcm' }).observe(fetchDuration)

        if (!fetchResponse || (status && status >= 400)) {
            const err = normalizeFcmError(status, body, fetchError)
            // Keep the raw provider response available for deep debugging, at debug level so it doesn't
            // clutter the workflow log — the user-facing explanation is the normalized message below.
            addLog('debug', `FCM response ${status ?? '(none)'}: ${stringifyBody(body)}`)
            if (err.unregistered) {
                this.pruneDeviceToken(result, invocation, params.distinctId, projectId, 'fcm')
                addLog('warn', `FCM: ${err.message}`)
                return false
            }
            throw pushSendError('fcm', err, parseRetryAfterMs(fetchResponse))
        }

        pushNotificationSentCounter.labels({ platform: 'fcm' }).inc()
        addLog('info', 'Push notification accepted by FCM.')
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
            pushNotificationSkippedCounter.labels({ platform: 'apns', reason: 'no_token' }).inc()
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
        pushNotificationSendDurationMs.labels({ platform: 'apns' }).observe(fetchDuration)

        if (!fetchResponse || (status && status >= 400)) {
            const err = normalizeApnsError(status, body, fetchError)
            addLog('debug', `APNs response ${status ?? '(none)'}: ${stringifyBody(body)}`)
            // Apple signals a dead token with 410 / reason "Unregistered". Prune it and skip rather than
            // retrying a token that will never work; other reasons are surfaced as failures.
            if (err.unregistered) {
                this.pruneDeviceToken(result, invocation, params.distinctId, bundleId, 'apns')
                addLog('warn', `APNs: ${err.message}`)
                return false
            }
            throw pushSendError('apns', err, parseRetryAfterMs(fetchResponse))
        }

        pushNotificationSentCounter.labels({ platform: 'apns' }).inc()
        addLog('info', 'Push notification accepted by APNs.')
        return true
    }

    private async generateApnsJwt(teamId: string, keyId: string, signingKey: string): Promise<string> {
        // Key the cache on a fingerprint of the signing-key material, not on the team id / key id — those
        // come from tenant-controlled integration config, so another team could set matching values to
        // collide with or poison this shared cache entry. Hashing the signing key makes the key unforgeable
        // while still letting the fleet reuse one token per signing key.
        const keyFingerprint = createHash('sha256').update(`${teamId}:${keyId}:${signingKey}`).digest('hex')
        const cacheKey = `${APNS_JWT_CACHE_PREFIX}${keyFingerprint}`

        const cached = await this.valkey.useClient({ name: 'apns-jwt-read', failOpen: true }, (client) =>
            client.get(cacheKey)
        )
        if (cached) {
            return cached
        }

        const local = this.apnsJwtLocalCache.get(cacheKey)
        if (local && local.expiresAtMs > Date.now()) {
            return local.jwt
        }

        const header = Buffer.from(JSON.stringify({ alg: 'ES256', kid: keyId })).toString('base64url')
        const now = Math.floor(Date.now() / 1000)
        const claims = Buffer.from(JSON.stringify({ iss: teamId, iat: now })).toString('base64url')
        const signingInput = `${header}.${claims}`
        const sign = createSign('SHA256')
        sign.update(signingInput)
        const signature = sign.sign({ key: signingKey, dsaEncoding: 'ieee-p1363' }, 'base64url')
        const jwt = `${signingInput}.${signature}`

        this.rememberApnsJwtLocally(cacheKey, jwt)
        await this.valkey.useClient({ name: 'apns-jwt-write', failOpen: true }, (client) =>
            client.set(cacheKey, jwt, 'EX', APNS_JWT_TTL_SECONDS)
        )
        return jwt
    }

    private rememberApnsJwtLocally(cacheKey: string, jwt: string): void {
        const nowMs = Date.now()
        this.apnsJwtLocalCache.set(cacheKey, { jwt, expiresAtMs: nowMs + APNS_JWT_TTL_SECONDS * 1000 })

        if (this.apnsJwtLocalCache.size <= APNS_JWT_LOCAL_CACHE_MAX) {
            return
        }
        for (const [key, entry] of this.apnsJwtLocalCache) {
            if (entry.expiresAtMs <= nowMs) {
                this.apnsJwtLocalCache.delete(key)
            }
        }
        // Map iterates in insertion order, so this drops the least recently minted. Safe because Valkey
        // is the real cache — a dropped entry only costs a signature during an outage.
        for (const key of this.apnsJwtLocalCache.keys()) {
            if (this.apnsJwtLocalCache.size <= APNS_JWT_LOCAL_CACHE_MAX) {
                break
            }
            this.apnsJwtLocalCache.delete(key)
        }
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

    // Remove a device token the provider reported as no longer registered. Emitted as a $unset person
    // update (flushed with the invocation's captured events) so we stop retrying dead tokens and don't
    // accumulate stale ones on the person.
    private pruneDeviceToken(
        result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>,
        invocation: CyclotronJobInvocationHogFunction,
        distinctId: string,
        appIdentifier: string,
        platform: 'fcm' | 'apns'
    ): void {
        result.capturedPostHogEvents.push({
            team_id: invocation.teamId,
            event: '$set',
            distinct_id: distinctId,
            timestamp: new Date().toISOString(),
            properties: { $unset: [`$device_push_subscription_${appIdentifier}`] },
        })
        pushNotificationTokenPrunedCounter.labels({ platform }).inc()
        // A dead token is a non-delivery, not a failure to fix. Record it in the reason-labeled skip
        // series too (not just the token-removal counter) so the skip metric accounts for it.
        pushNotificationSkippedCounter.labels({ platform, reason: 'unregistered' }).inc()
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
                // FCM's message.notification has no `subtitle`. For an iOS device delivered via FCM the
                // subtitle must live in the APNS alert; include title/body so overriding the alert keeps them.
                aps.alert = {
                    title: payload.title,
                    ...(payload.body ? { body: payload.body } : {}),
                    subtitle: payload.apns.subtitle,
                }
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
