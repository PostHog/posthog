import { LogEntryLevel } from '../../types'

export type PushPlatform = 'fcm' | 'apns'

// A normalized, provider-agnostic reason a push send didn't land. Kept to a small, bounded set so it
// can safely label ops metrics, and so the workflow logs can explain *why* a push failed in plain
// language instead of dumping a raw FCM/APNs error payload at the user.
export type PushFailureReason =
    | 'unregistered' // the token is dead: app uninstalled or token rotated (permanent)
    | 'invalid_token' // the token is malformed or not valid for this app/topic
    | 'auth_error' // the integration's credentials were rejected by the provider
    | 'rate_limited' // the provider is throttling this project/topic
    | 'invalid_payload' // the provider rejected the message contents
    | 'provider_error' // a transient server-side failure at the provider (5xx)
    | 'network_error' // the request never reached the provider
    | 'unknown'

export type NormalizedPushError = {
    reason: PushFailureReason
    // The raw provider code (FCM errorCode/status or APNs reason), for debugging. Undefined if none was returned.
    code?: string
    // Whether this means the device token should be removed from the person (a permanent, dead token).
    unregistered: boolean
    // Whether the send is worth retrying: transient provider/network problems are, config/content ones aren't.
    retriable: boolean
    // Log severity: config problems the user must fix are errors; transient/expected ones are warnings.
    level: LogEntryLevel
    // A plain-language explanation for the workflow logs.
    message: string
}

// Thrown by a channel send when it fails. Carries the normalized reason, severity, retriability, and the
// provider's Retry-After (when given) so the caller can log once at the right level, label metrics, and
// decide whether to reschedule the whole invocation, without re-deriving any of it or double-logging.
export class PushSendError extends Error {
    constructor(
        message: string,
        public readonly platform: PushPlatform,
        public readonly reason: PushFailureReason,
        public readonly level: LogEntryLevel,
        public readonly retriable: boolean,
        public readonly code?: string,
        public readonly retryAfterMs?: number
    ) {
        super(message)
        this.name = 'PushSendError'
    }
}

const PLATFORM_LABEL: Record<PushPlatform, string> = { fcm: 'FCM', apns: 'APNs' }

// Config problems a user must fix surface as errors; transient or self-resolving ones as warnings.
const REASON_LEVEL: Record<PushFailureReason, LogEntryLevel> = {
    unregistered: 'warn',
    invalid_token: 'error',
    auth_error: 'error',
    rate_limited: 'warn',
    invalid_payload: 'error',
    provider_error: 'warn',
    network_error: 'warn',
    unknown: 'error',
}

// Only transient provider/network problems are worth retrying. Config and content problems (bad
// credentials, invalid token, rejected payload) will fail the same way on every attempt, and an
// unregistered token is handled by pruning rather than retrying.
const REASON_RETRIABLE: Record<PushFailureReason, boolean> = {
    unregistered: false,
    invalid_token: false,
    auth_error: false,
    rate_limited: true,
    invalid_payload: false,
    provider_error: true,
    network_error: true,
    unknown: false,
}

// The user-facing sentence for each reason. Written to guide the next action, not just state the fault.
function reasonMessage(platform: PushPlatform, reason: PushFailureReason): string {
    const provider = PLATFORM_LABEL[platform]
    switch (reason) {
        case 'unregistered':
            return 'The device is no longer reachable. The app was uninstalled or the push token expired, so the token has been removed and will not be retried.'
        case 'invalid_token':
            return `${provider} rejected the device token as invalid for this app. Check that the device registered against the same ${platform === 'fcm' ? 'Firebase project' : 'APNs topic (bundle id)'}.`
        case 'auth_error':
            return `${provider} rejected the integration credentials. Check the ${platform === 'fcm' ? 'Firebase service account key' : 'APNs signing key, key id, and team id'} in the integration settings.`
        case 'rate_limited':
            return `${provider} is rate-limiting this ${platform === 'fcm' ? 'project' : 'topic'}. The notification was not delivered on this attempt.`
        case 'invalid_payload':
            return `${provider} rejected the notification contents. Check the title, body, and any custom data on the push step.`
        case 'provider_error':
            return `${provider} had a temporary server error and could not accept the notification.`
        case 'network_error':
            return `The request to ${provider} could not be completed (network error).`
        case 'unknown':
            return `${provider} returned an unexpected error.`
    }
}

function build(platform: PushPlatform, reason: PushFailureReason, code: string | undefined): NormalizedPushError {
    return {
        reason,
        code,
        unregistered: reason === 'unregistered',
        retriable: REASON_RETRIABLE[reason],
        level: REASON_LEVEL[reason],
        message: reasonMessage(platform, reason),
    }
}

// FCM v1 returns `{ error: { status, message, details: [{ errorCode }] } }`. The per-message `errorCode`
// in details is the most specific signal; fall back to the canonical `error.status`, then the HTTP status.
export function normalizeFcmError(
    status: number | undefined,
    body: unknown,
    fetchError: Error | null
): NormalizedPushError {
    if (fetchError && !status) {
        return build('fcm', 'network_error', undefined)
    }

    const error = (body as any)?.error
    const errorCode: string | undefined =
        error?.details?.find?.((d: any) => typeof d?.errorCode === 'string')?.errorCode ?? undefined
    const canonical: string | undefined = typeof error?.status === 'string' ? error.status : undefined
    const code = errorCode ?? canonical

    // Only treat this as a dead token when FCM itself says so (the UNREGISTERED errorCode, or the
    // NOT_FOUND canonical status). A bare HTTP 404 with no FCM error body can come from a proxy or a
    // misconfigured endpoint, and pruning on that would permanently drop a still-valid device token.
    if (errorCode === 'UNREGISTERED' || canonical === 'NOT_FOUND') {
        return build('fcm', 'unregistered', code)
    }
    if (errorCode === 'SENDER_ID_MISMATCH' || errorCode === 'THIRD_PARTY_AUTH_ERROR') {
        return build('fcm', 'auth_error', code)
    }
    if (errorCode === 'QUOTA_EXCEEDED' || errorCode === 'MESSAGE_RATE_EXCEEDED' || status === 429) {
        return build('fcm', 'rate_limited', code)
    }
    if (canonical === 'UNAUTHENTICATED' || canonical === 'PERMISSION_DENIED' || status === 401 || status === 403) {
        return build('fcm', 'auth_error', code)
    }
    if (errorCode === 'INVALID_ARGUMENT' || canonical === 'INVALID_ARGUMENT' || status === 400) {
        return build('fcm', 'invalid_payload', code)
    }
    if (status !== undefined && status >= 500) {
        return build('fcm', 'provider_error', code)
    }
    return build('fcm', 'unknown', code)
}

// APNs returns `{ reason: "..." }` (and a `410` status for unregistered tokens). The reason string is
// the authoritative signal; the HTTP status backs it up for throttling and server errors.
export function normalizeApnsError(
    status: number | undefined,
    body: unknown,
    fetchError: Error | null
): NormalizedPushError {
    if (fetchError && !status) {
        return build('apns', 'network_error', undefined)
    }

    const reason: string | undefined =
        body && typeof body === 'object' && typeof (body as any).reason === 'string' ? (body as any).reason : undefined

    if (reason === 'Unregistered' || status === 410) {
        return build('apns', 'unregistered', reason)
    }
    if (reason === 'BadDeviceToken' || reason === 'DeviceTokenNotForTopic' || reason === 'MissingDeviceToken') {
        return build('apns', 'invalid_token', reason)
    }
    if (
        reason === 'InvalidProviderToken' ||
        reason === 'ExpiredProviderToken' ||
        reason === 'MissingProviderToken' ||
        reason === 'TopicDisallowed' ||
        reason === 'Forbidden'
    ) {
        return build('apns', 'auth_error', reason)
    }
    if (reason === 'TooManyRequests' || reason === 'TooManyProviderTokenUpdates' || status === 429) {
        return build('apns', 'rate_limited', reason)
    }
    if (
        reason === 'PayloadTooLarge' ||
        reason === 'PayloadEmpty' ||
        reason === 'BadExpirationDate' ||
        reason === 'BadPriority' ||
        reason === 'BadTopic'
    ) {
        return build('apns', 'invalid_payload', reason)
    }
    if (
        reason === 'InternalServerError' ||
        reason === 'ServiceUnavailable' ||
        (status !== undefined && status >= 500)
    ) {
        return build('apns', 'provider_error', reason)
    }
    return build('apns', 'unknown', reason)
}
