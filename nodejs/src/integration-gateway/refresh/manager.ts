import { EncryptedFields } from '~/common/utils/encryption-utils'
import { logger } from '~/common/utils/logger'
import { fetch } from '~/common/utils/request'
import { RedisPool } from '~/types'

import { RefreshTeamGate } from '../config'
import { recordRefresh } from '../metrics'
import { IntegrationRepository } from '../repository'
import { IntegrationRow } from '../types'
import { accessTokenExpired, nowSecs } from './expiry'
import { Provider, ProviderCredentials, providerFor } from './providers'

interface TokenResponse {
    access_token?: string
    expires_in?: number
    refresh_token?: string
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
            const updated = await this.refreshLocked(row, provider)
            await this.releaseLock(lockKey)
            recordRefresh(row.kind, 'refreshed')
            return updated
        } catch (error) {
            // Deliberately do NOT release the lock on failure: its TTL becomes a per-integration
            // cooldown so a persistently-failing provider is retried at most once per lock window
            // rather than on every fetch — a lightweight stand-in for Django's refresh backoff.
            logger.warn('[RefreshManager] token refresh failed', { id: row.id, kind: row.kind, error: String(error) })
            try {
                await this.repository.markRefreshFailed(row.id)
            } catch (markError) {
                logger.warn('[RefreshManager] failed to record refresh error', {
                    id: row.id,
                    error: String(markError),
                })
            }
            recordRefresh(row.kind, 'failed')
            return row
        }
    }

    private async refreshLocked(row: IntegrationRow, provider: Provider): Promise<IntegrationRow> {
        // Re-read under the lock: a concurrent head (or Django) may have just rotated the token.
        const fresh = (await this.repository.fetchOne(row.id)) ?? row
        if (!accessTokenExpired(fresh.kind, fresh.config)) {
            return fresh
        }

        const refreshToken = this.decryptRefreshToken(fresh)
        const tokens = await this.requestRefresh(provider, refreshToken)

        // Some providers omit expires_in on refresh; Django assumes 3600s for Salesforce/Stripe.
        let expiresIn: number | null
        if (typeof tokens.expires_in === 'number') {
            expiresIn = tokens.expires_in
        } else if (fresh.kind === 'salesforce' || fresh.kind === 'stripe') {
            expiresIn = 3600
        } else {
            expiresIn = null
        }

        const newConfig = { ...fresh.config, refreshed_at: Math.floor(nowSecs()), expires_in: expiresIn }
        // Overwrite only the rotated leaves; other (still-encrypted) leaves are left untouched.
        const newSensitiveConfig: Record<string, any> = {
            ...fresh.sensitive_config,
            access_token: this.encryptedFields.encrypt(tokens.access_token!),
        }
        if (tokens.refresh_token) {
            newSensitiveConfig.refresh_token = this.encryptedFields.encrypt(tokens.refresh_token)
        }

        await this.repository.updateAfterRefresh(fresh.id, newConfig, newSensitiveConfig)

        return { ...fresh, config: newConfig, sensitive_config: newSensitiveConfig }
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

    private async requestRefresh(provider: Provider, refreshToken: string): Promise<TokenResponse> {
        const body = new URLSearchParams({
            grant_type: 'refresh_token',
            refresh_token: refreshToken,
            client_id: provider.clientId,
            client_secret: provider.clientSecret,
        }).toString()

        const response = await fetch(provider.tokenUrl, {
            method: 'POST',
            headers: { 'content-type': 'application/x-www-form-urlencoded' },
            body,
            timeoutMs: this.config.INTEGRATION_GATEWAY_REFRESH_HTTP_TIMEOUT_MS,
        })

        if (response.status < 200 || response.status >= 300) {
            const text = await response.text()
            throw new Error(`provider returned ${response.status}: ${text}`)
        }

        const parsed = (await response.json()) as TokenResponse
        if (!parsed.access_token) {
            throw new Error('provider response had no access_token')
        }
        return parsed
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
