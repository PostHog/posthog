import { nowSecs } from './expiry'

/**
 * Consecutive-failure backoff + terminal detection for JIT refresh, mirroring Django's
 * `record_refresh_failure` / `record_refresh_success` / `refresh_backoff_active`
 * (posthog/models/integration.py). Same config keys and semantics, so a row is read/written
 * identically whether Django's beat or the gateway last touched it.
 *
 * Without this, a permanently-dead integration (revoked grant) is retried on every read forever,
 * hammering the provider and flapping the customer's "reconnect" banner.
 */
export const REFRESH_BACKOFF_BASE_SECONDS = 120
export const REFRESH_BACKOFF_MAX_SECONDS = 3600
export const REFRESH_TERMINAL_FAILURE_COUNT = 5

export type RefreshFailureReason = 'invalid_grant' | 'invalid_client' | 'http_5xx' | 'network' | 'other'

/** Whether refresh should be skipped for this row right now (terminal, or inside a backoff window). */
export function refreshBackoffActive(config: Record<string, any>): boolean {
    if (config?.refresh_terminal) {
        return true
    }
    const nextAttemptAt = config?.refresh_next_attempt_at
    return typeof nextAttemptAt === 'number' && nowSecs() < nextAttemptAt
}

/**
 * Bucket an OAuth refresh failure. `status === null` means the request never got a response
 * (network error/timeout). Mirrors Django's `oauth_refresh_failure_reason`.
 */
export function refreshFailureReason(status: number | null, body: any, kind: string): RefreshFailureReason {
    if (status === null) {
        return 'network'
    }
    const error = body?.error
    if (error === 'invalid_grant') {
        return 'invalid_grant'
    }
    if (error === 'invalid_client') {
        return 'invalid_client'
    }
    // Reddit reports a dead grant as `{"message":"Bad Request","error":400}` with no OAuth error code.
    if (kind === 'reddit-ads' && status === 400 && error === 400) {
        return 'invalid_grant'
    }
    if (status >= 500) {
        return 'http_5xx'
    }
    return 'other'
}

/**
 * Return a NEW config with one consecutive failure recorded: bumps `refresh_failure_count`, schedules
 * `refresh_next_attempt_at` with capped exponential backoff, and — only for an unbroken `invalid_grant`
 * streak (a dead grant only a re-auth can fix) — flips `refresh_terminal` after
 * REFRESH_TERMINAL_FAILURE_COUNT. Any non-grant reason resets the streak, so a transient 5xx amid the
 * streak can't brick the integration. Does not mutate the input.
 */
export function recordRefreshFailure(config: Record<string, any>, reason: RefreshFailureReason): Record<string, any> {
    const next = { ...config }
    const count = (Number(next.refresh_failure_count) || 0) + 1
    next.refresh_failure_count = count
    next.refresh_next_attempt_at =
        Math.floor(nowSecs()) + Math.min(REFRESH_BACKOFF_BASE_SECONDS * 2 ** (count - 1), REFRESH_BACKOFF_MAX_SECONDS)
    if (reason === 'invalid_grant') {
        const grantStreak = (Number(next.refresh_invalid_grant_count) || 0) + 1
        next.refresh_invalid_grant_count = grantStreak
        if (grantStreak >= REFRESH_TERMINAL_FAILURE_COUNT) {
            next.refresh_terminal = true
        }
    } else {
        delete next.refresh_invalid_grant_count
    }
    return next
}

/** Return a NEW config with all backoff/terminal state cleared after a successful refresh. */
export function recordRefreshSuccess(config: Record<string, any>): Record<string, any> {
    const next = { ...config }
    delete next.refresh_failure_count
    delete next.refresh_invalid_grant_count
    delete next.refresh_next_attempt_at
    delete next.refresh_terminal
    return next
}
