import { EncryptedFields } from '~/common/utils/encryption-utils'
import { logger } from '~/common/utils/logger'
import { fetch } from '~/common/utils/request'
import { RedisPool } from '~/types'

import { RefreshTeamGate } from '../config'
import { recordRefresh } from '../metrics'
import { IntegrationRepository } from '../repository'
import { IntegrationRow } from '../types'
import {
    RefreshFailureReason,
    recordRefreshFailure,
    recordRefreshSuccess,
    refreshBackoffActive,
    refreshFailureReason,
} from './backoff'
import { accessTokenExpired, nowSecs } from './expiry'
import { Provider, ProviderCredentials, providerFor } from './providers'

interface TokenResponse {
    access_token?: string
    expires_in?: number
    refresh_token?: string
}

/** Outcome of one refresh attempt, used for the metric label. */
type RefreshOutcome = 'refreshed' | 'failed' | 'skipped' | 'backoff' | 'superseded'

interface RefreshLockedResult {
    row: IntegrationRow
    outcome: RefreshOutcome
}

export type RefreshManagerConfig = ProviderCredentials & {
    INTEGRATION_GATEWAY_REFRESH_KINDS: string
    INTEGRATION_GATEWAY_REFRESH_LOCK_TTL_SECONDS: number
    INTEGRATION_GATEWAY_REFRESH_HTTP_TIMEOUT_MS: number
}

/**
 * Owns just-in-time OAuth token refresh for rows whose kind is in `INTEGRATION_GATEWAY_REFRESH_KINDS`
 * (capability contract) AND whose team is in `INTEGRATION_GATEWAY_REFRESH_TEAMS` (rollout gate).
 * Single-flight per integration via a Redis lock, so only one head refreshes a given row at a time
 * (important for providers that rotate the refresh token). Django's beat MUST exclude exactly the
 * same (kind, team) rows so every row has precisely one refresher.
 */
export class RefreshManager {
    private ownedKinds: Set<string>

    constructor(
        private repository: IntegrationRepository,
        private encryptedFields: EncryptedFields,
        private redisPool: RedisPool,
        private config: RefreshManagerConfig,
        ownedKinds: string[],
        private ownedTeams: RefreshTeamGate
    ) {
        this.ownedKinds = new Set(ownedKinds)
    }

    owns(kind: string, teamId: number): boolean {
        if (!this.ownedKinds.has(kind)) {
            return false
        }
        return this.ownedTeams === '*' || this.ownedTeams.has(teamId)
    }

    /**
     * Refresh `row` if its access token is past half-life, returning the (possibly updated) row with
     * re-encrypted credentials. Fail-open: on any error the input row is returned unchanged, so the
     * read path still serves the existing (still-valid, since we refresh proactively) token.
     */
    async refresh(row: IntegrationRow): Promise<IntegrationRow> {
        if (!accessTokenExpired(row.kind, row.config)) {
            return row
        }

        // Honor the persisted backoff/terminal state (same fields Django's beat writes) before doing
        // any work: a dead grant or an in-window failure must not be retried on every read.
        if (refreshBackoffActive(row.config)) {
            recordRefresh(row.kind, 'backoff')
            return row
        }

        const provider = providerFor(row.kind, this.config, row.config)
        if (!provider) {
            logger.warn('[RefreshManager] refresh requested but no provider/credentials configured; skipping', {
                id: row.id,
                kind: row.kind,
            })
            recordRefresh(row.kind, 'skipped')
            return row
        }

        // No stored refresh_token => nothing to refresh. Skip (don't mark failed), mirroring Django's
        // access_token_expired, which returns false when there's no refresh_token.
        if (typeof row.sensitive_config?.refresh_token !== 'string') {
            recordRefresh(row.kind, 'skipped')
            return row
        }

        const lockKey = `integration-gateway:refresh-lock:${row.id}`
        let acquired: boolean
        try {
            acquired = await this.acquireLock(lockKey)
        } catch (error) {
            logger.warn('[RefreshManager] failed to acquire refresh lock; skipping', {
                id: row.id,
                error: String(error),
            })
            recordRefresh(row.kind, 'skipped')
            return row
        }
        if (!acquired) {
            // Another head holds the lock; the current token is still valid (half-life refresh).
            recordRefresh(row.kind, 'locked')
            return row
        }

        try {
            const { row: updated, outcome } = await this.refreshLocked(row, provider)
            recordRefresh(row.kind, outcome)
            return updated
        } catch (error) {
            // Backstop for unexpected errors (DB/lock); persisted backoff handles per-provider
            // cooldown so we can safely release the lock in `finally` and fail open.
            logger.warn('[RefreshManager] unexpected error during refresh', {
                id: row.id,
                kind: row.kind,
                error: String(error),
            })
            recordRefresh(row.kind, 'failed')
            return row
        } finally {
            await this.releaseLock(lockKey)
        }
    }

    private async refreshLocked(row: IntegrationRow, provider: Provider): Promise<RefreshLockedResult> {
        // Re-read under the lock from the primary: a concurrent head (or Django) may have just
        // rotated the token or recorded backoff, and a replica read could miss that.
        const fresh = (await this.repository.fetchOneForUpdate(row.id)) ?? row
        if (!accessTokenExpired(fresh.kind, fresh.config)) {
            return { row: fresh, outcome: 'skipped' }
        }
        if (refreshBackoffActive(fresh.config)) {
            return { row: fresh, outcome: 'backoff' }
        }
        if (typeof fresh.sensitive_config?.refresh_token !== 'string') {
            return { row: fresh, outcome: 'skipped' }
        }

        // The exact stored ciphertext we're about to spend — used as the compare-and-swap guard so a
        // concurrent Django reconnect can't be clobbered (see repository.updateAfterRefresh).
        const storedRefreshToken = fresh.sensitive_config.refresh_token
        let refreshToken: string
        try {
            refreshToken = this.decryptRefreshToken(fresh)
        } catch (error) {
            logger.warn('[RefreshManager] stored refresh_token is not decryptable', {
                id: fresh.id,
                error: String(error),
            })
            return await this.recordFailure(fresh, storedRefreshToken, 'other')
        }

        const { status, body } = await this.requestRefresh(provider, refreshToken)
        if (status === null || status < 200 || status >= 300 || typeof body?.access_token !== 'string') {
            return await this.recordFailure(fresh, storedRefreshToken, refreshFailureReason(status, body, fresh.kind))
        }
        const tokens = body as TokenResponse

        // Some providers omit expires_in on refresh; Django assumes 3600s for Salesforce/Stripe.
        let expiresIn: number | null
        if (typeof tokens.expires_in === 'number') {
            expiresIn = tokens.expires_in
        } else if (fresh.kind === 'salesforce' || fresh.kind === 'stripe') {
            expiresIn = 3600
        } else {
            expiresIn = null
        }

        // Clear any prior backoff/terminal state on success (mirrors Django's record_refresh_success).
        const newConfig = recordRefreshSuccess({
            ...fresh.config,
            refreshed_at: Math.floor(nowSecs()),
            expires_in: expiresIn,
        })
        // Overwrite only the rotated leaves; other (still-encrypted) leaves are left untouched.
        const newSensitiveConfig: Record<string, any> = {
            ...fresh.sensitive_config,
            access_token: this.encryptedFields.encrypt(tokens.access_token!),
        }
        if (tokens.refresh_token) {
            newSensitiveConfig.refresh_token = this.encryptedFields.encrypt(tokens.refresh_token)
        }

        const persisted = await this.repository.updateAfterRefresh(
            fresh.id,
            newConfig,
            newSensitiveConfig,
            storedRefreshToken
        )
        if (!persisted) {
            // Lost the race: the row changed since we read it (e.g. a user reconnect rotated the
            // token). Discard our now-stale refresh and serve whatever the winner persisted.
            logger.info('[RefreshManager] refresh superseded by a concurrent write; discarding', {
                id: fresh.id,
                kind: fresh.kind,
            })
            return { row: (await this.repository.fetchOneForUpdate(fresh.id)) ?? fresh, outcome: 'superseded' }
        }

        return { row: { ...fresh, config: newConfig, sensitive_config: newSensitiveConfig }, outcome: 'refreshed' }
    }

    /**
     * Record a refresh failure with capped exponential backoff + terminal detection (Django parity),
     * compare-and-swap guarded so a concurrent reconnect isn't overwritten with stale failure state.
     * Fail-open: the caller still serves the existing token.
     */
    private async recordFailure(
        fresh: IntegrationRow,
        storedRefreshToken: string,
        reason: RefreshFailureReason
    ): Promise<RefreshLockedResult> {
        logger.warn('[RefreshManager] token refresh failed', { id: fresh.id, kind: fresh.kind, reason })
        const failedConfig = recordRefreshFailure(fresh.config, reason)
        try {
            const persisted = await this.repository.recordRefreshFailure(fresh.id, failedConfig, storedRefreshToken)
            if (!persisted) {
                logger.info('[RefreshManager] failure superseded by a concurrent write; discarding', {
                    id: fresh.id,
                    kind: fresh.kind,
                })
                return { row: (await this.repository.fetchOneForUpdate(fresh.id)) ?? fresh, outcome: 'superseded' }
            }
        } catch (markError) {
            logger.warn('[RefreshManager] failed to record refresh error', {
                id: fresh.id,
                error: String(markError),
            })
        }
        return { row: fresh, outcome: 'failed' }
    }

    private decryptRefreshToken(row: IntegrationRow): string {
        const encrypted = row.sensitive_config?.refresh_token
        if (typeof encrypted !== 'string') {
            throw new Error('integration has no stored refresh_token')
        }
        let decrypted: string | undefined
        try {
            decrypted = this.encryptedFields.decrypt(encrypted)
        } catch {
            decrypted = undefined
        }
        if (decrypted === undefined) {
            throw new Error('integration refresh_token is not decryptable')
        }
        return decrypted
    }

    /**
     * POST the refresh grant. Returns the HTTP status and parsed JSON body (for failure
     * classification); `status: null` signals a network error/timeout (no response), which the
     * caller buckets as a transient `network` failure rather than a terminal one.
     */
    private async requestRefresh(
        provider: Provider,
        refreshToken: string
    ): Promise<{ status: number | null; body: any }> {
        const body = new URLSearchParams({
            grant_type: 'refresh_token',
            refresh_token: refreshToken,
            client_id: provider.clientId,
            client_secret: provider.clientSecret,
        }).toString()

        try {
            const response = await fetch(provider.tokenUrl, {
                method: 'POST',
                headers: { 'content-type': 'application/x-www-form-urlencoded' },
                body,
                timeoutMs: this.config.INTEGRATION_GATEWAY_REFRESH_HTTP_TIMEOUT_MS,
            })
            let parsed: any = {}
            try {
                parsed = await response.json()
            } catch {
                // Non-JSON error body (some providers return HTML/text on 5xx) — status still classifies it.
                parsed = {}
            }
            return { status: response.status, body: parsed }
        } catch (error) {
            logger.warn('[RefreshManager] network error during token refresh', { error: String(error) })
            return { status: null, body: {} }
        }
    }

    private async acquireLock(key: string): Promise<boolean> {
        const client = await this.redisPool.acquire()
        try {
            const result = (await client.set(
                key,
                '1',
                'EX',
                this.config.INTEGRATION_GATEWAY_REFRESH_LOCK_TTL_SECONDS,
                'NX'
            )) as 'OK' | null
            return result === 'OK'
        } finally {
            await this.redisPool.release(client)
        }
    }

    private async releaseLock(key: string): Promise<void> {
        try {
            const client = await this.redisPool.acquire()
            try {
                await client.del(key)
            } finally {
                await this.redisPool.release(client)
            }
        } catch (error) {
            // Best-effort; the lock TTL-expires on its own.
            logger.warn('[RefreshManager] failed to release refresh lock', { key, error: String(error) })
        }
    }
}
