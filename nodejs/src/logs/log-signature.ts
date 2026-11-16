import { createHmac, timingSafeEqual } from 'crypto'
import { Counter } from 'prom-client'

import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'

import type { EncryptedFields } from '../cdp/utils/encryption-utils'
import { SIGNATURE_VERSION, SIGNATURE_WINDOW_SECONDS, SIGNED_AT_PATTERN } from './internal-logs'

export const LOGS_SIGNATURE_HEADER = 'posthog-signature'

// The HTTP request header that capture-logs forwards as the `posthog-signature` Kafka header.
export const LOGS_SIGNATURE_HTTP_HEADER = 'x-posthog-signature'

// The Kafka MV copies this header to the `signature_status` column.
export const SIGNATURE_STATUS_HEADER = 'signature-status'
export const SIGNATURE_STATUS_VERIFIED = 'verified'

// Must match `LogsSigningSecret.PREVIOUS_SECRET_GRACE` in `products/logs/backend/models.py`.
const PREVIOUS_SECRET_GRACE_MS = 48 * 60 * 60 * 1000

// A rotated secret takes up to this long to apply.
const REFRESH_MS = 30_000
const FAILED_REFRESH_RETRY_MS = 5_000

type UnverifiedReason = 'no_secret' | 'invalid_signature' | 'stale_signature'

const logsSignatureCounter = new Counter({
    name: 'logs_ingestion_signature_total',
    help: 'Batches that carried the posthog-signature header, by outcome. An unverified batch is stored unmarked.',
    labelNames: ['outcome', 'reason'],
})

// No payload hash, because capture-logs re-encodes the request and the customer never sees the Kafka bytes.
function computeSignature(secret: string, teamId: number, signedAt: string): string {
    const mac = createHmac('sha256', secret).update(`${SIGNATURE_VERSION}|${teamId}|${signedAt}`).digest('hex')
    return `${SIGNATURE_VERSION}.${signedAt}.${mac}`
}

export function signLogs(secret: string, teamId: number, signedAt: Date = new Date()): string {
    return computeSignature(secret, teamId, String(Math.floor(signedAt.getTime() / 1000)))
}

/** The secrets a signature may use: the current one, then the previous one while its grace period lasts. */
export interface LogsSigningSecretsSource {
    getSecrets(teamId: number): Promise<readonly string[]>
}

type CacheEntry = { secrets: readonly string[]; expiresAtMs: number }

export class LogsSigningSecretsCache implements LogsSigningSecretsSource {
    private cache = new Map<number, CacheEntry>()
    private inflight = new Map<number, Promise<readonly string[]>>()

    constructor(
        private postgres: PostgresRouter,
        private encryptedFields: EncryptedFields
    ) {}

    public async getSecrets(teamId: number): Promise<readonly string[]> {
        const existing = this.cache.get(teamId)
        if (existing && Date.now() < existing.expiresAtMs) {
            return existing.secrets
        }
        // Messages are processed concurrently, so share one refresh per team.
        let refresh = this.inflight.get(teamId)
        if (!refresh) {
            refresh = this.refresh(teamId, existing).finally(() => this.inflight.delete(teamId))
            this.inflight.set(teamId, refresh)
        }
        return refresh
    }

    // A failed fetch never throws, because a signature must not block or quarantine a batch.
    private async refresh(teamId: number, existing: CacheEntry | undefined): Promise<readonly string[]> {
        try {
            const secrets = await this.fetchSecrets(teamId)
            this.cache.set(teamId, { secrets, expiresAtMs: Date.now() + REFRESH_MS })
            return secrets
        } catch (error) {
            logger.warn('[logs-signature] signing secret fetch failed', { teamId, error: String(error) })
            const fallback = existing?.secrets ?? []
            // Hold the fallback briefly so a down database is not queried on every message.
            this.cache.set(teamId, { secrets: fallback, expiresAtMs: Date.now() + FAILED_REFRESH_RETRY_MS })
            return fallback
        }
    }

    private async fetchSecrets(teamId: number): Promise<readonly string[]> {
        const res = await this.postgres.query<{
            secret: string
            previous_secret: string | null
            previous_secret_rotated_at: Date | null
        }>(
            PostgresUse.COMMON_READ,
            `SELECT secret, previous_secret, previous_secret_rotated_at FROM logs_logssigningsecret WHERE team_id = $1`,
            [teamId],
            'logs-signing-secret-fetch'
        )
        const row = res.rows[0]
        if (!row) {
            return []
        }
        const previousActive =
            row.previous_secret !== null &&
            row.previous_secret_rotated_at !== null &&
            Date.now() < new Date(row.previous_secret_rotated_at).getTime() + PREVIOUS_SECRET_GRACE_MS
        return [row.secret, ...(previousActive && row.previous_secret ? [row.previous_secret] : [])].flatMap(
            (encrypted) => {
                const decrypted = this.encryptedFields.tryDecrypt(encrypted)
                return decrypted.ok ? [decrypted.value] : []
            }
        )
    }
}

function unverifiedReason(
    signature: string,
    secrets: readonly string[],
    teamId: number,
    createdAt: string | undefined
): UnverifiedReason | null {
    if (secrets.length === 0) {
        return 'no_secret'
    }
    const [, signedAt = ''] = signature.split('.')
    if (!SIGNED_AT_PATTERN.test(signedAt)) {
        return 'invalid_signature'
    }
    const received = Buffer.from(signature)
    const matches = secrets.some((secret) => {
        const expected = Buffer.from(computeSignature(secret, teamId, signedAt))
        return expected.length === received.length && timingSafeEqual(expected, received)
    })
    if (!matches) {
        return 'invalid_signature'
    }
    // A missing or unparseable `created_at` gives NaN, which fails this comparison.
    const skewSeconds = Math.abs(Date.parse(createdAt ?? '') / 1000 - Number(signedAt))
    return skewSeconds <= SIGNATURE_WINDOW_SECONDS ? null : 'stale_signature'
}

/** `createdAt` is the `created_at` Kafka header, which capture-logs sets when it receives the request. */
export async function verifyLogsSignature(
    source: LogsSigningSecretsSource | undefined,
    signature: string | undefined,
    teamId: number,
    createdAt: string | undefined
): Promise<boolean> {
    if (signature === undefined || !source) {
        return false
    }
    const reason = unverifiedReason(signature, await source.getSecrets(teamId), teamId, createdAt)
    // The team is not a counter label, because any sender can set the header.
    logsSignatureCounter.inc({ outcome: reason ? 'unverified' : 'verified', reason: reason ?? '' })
    return reason === null
}

// Only a verified batch may set the `signature_status` column, so an incoming copy of the header is removed.
export function withSignatureStatus(headers: Record<string, string>, verified: boolean): Record<string, string> {
    const { [LOGS_SIGNATURE_HEADER]: _signature, [SIGNATURE_STATUS_HEADER]: _status, ...rest } = headers
    return verified ? { ...rest, [SIGNATURE_STATUS_HEADER]: SIGNATURE_STATUS_VERIFIED } : rest
}
