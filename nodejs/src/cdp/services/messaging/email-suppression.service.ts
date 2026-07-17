import { Counter } from 'prom-client'

import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'

const cdpEmailSuppressionTotal = new Counter({
    name: 'cdp_email_suppression_total',
    help: 'Email suppression-list outcomes. `suppressed_hit` = a send skipped because the recipient is on the list; `transient_bounce` = a soft-bounce counter increment; `hard_bounce` = an address suppressed immediately after a permanent bounce.',
    labelNames: ['result'],
})

const DIAGNOSTIC_MAX_LENGTH = 1000

const normalizeIdentifier = (email: string): string => email.trim().toLowerCase()

const toKey = (teamId: number, identifier: string): string => `${teamId}:${identifier}`

export type EmailSuppressionConfig = {
    // Populate the list on soft bounces / hard bounces / deliveries.
    writeEnabled: boolean
    // Skip sends to suppressed recipients (pre-send hook).
    enforceEnabled: boolean
    // Consecutive soft bounces before auto-suppression.
    transientBounceThreshold: number
}

// Test helper — production paths take config from `CdpConfig`; tests that still mutate process.env
// can call this to construct the same shape without duplicating the parse logic.
export function emailSuppressionConfigFromEnv(): EmailSuppressionConfig {
    const flagOn = (value: string | undefined): boolean => value === '1' || value?.toLowerCase() === 'true'
    const rawThreshold = process.env.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD
    const parsedThreshold = rawThreshold ? parseInt(rawThreshold, 10) : NaN
    return {
        writeEnabled: flagOn(process.env.EMAIL_SUPPRESSION_WRITE_ENABLED),
        enforceEnabled: flagOn(process.env.EMAIL_SUPPRESSION_ENFORCE_ENABLED),
        transientBounceThreshold: Number.isFinite(parsedThreshold) && parsedThreshold > 0 ? parsedThreshold : 5,
    }
}

/**
 * Per-team email suppression list, backed by `posthog_messagesuppression`.
 *
 * Read path (pre-send): `isSuppressed` is consulted before every email send so we skip
 * addresses that can't (or shouldn't) receive mail. Cached via LazyLoader so a big batch to the
 * same recipients doesn't hammer Postgres.
 *
 * Write path (SES webhook): `recordTransientBounces` counts consecutive soft bounces per address
 * and flips it to suppressed once the count crosses the threshold; `recordDeliveries` resets the
 * count on any successful delivery so a one-off outage never accumulates into a suppression.
 * Manual entries (added via the API/UI) are never touched by the bounce/delivery bookkeeping.
 *
 * Cache invalidation window (v1):
 *   The LazyLoader cache is per-process. `clear()` only fires on the Node process that performed
 *   the write, so manual add/remove via the Django API (which never touches Node) and bounce writes
 *   handled by a different worker won't invalidate other workers' caches immediately. Effect:
 *   suppression state can be stale for up to LazyLoader's refresh window (~5 minutes) on other pods.
 *   The pre-send check may allow a send to a just-suppressed address, or block a send to a
 *   just-removed one, for that window. Acceptable for v1 given the low rate of state changes; a
 *   follow-up should propagate invalidations via pubsub (see `IntegrationManagerService` for the
 *   pattern) if the staleness becomes a support issue.
 */
export class EmailSuppressionService {
    private readonly threshold: number
    private readonly writeEnabled: boolean
    private readonly enforceEnabled: boolean
    private readonly lazyLoader: LazyLoader<boolean>

    constructor(
        private postgres: PostgresRouter,
        config: EmailSuppressionConfig
    ) {
        this.writeEnabled = config.writeEnabled
        this.enforceEnabled = config.enforceEnabled
        this.threshold = config.transientBounceThreshold
        this.lazyLoader = new LazyLoader({
            name: 'email_suppression',
            loader: async (keys) => await this.loadSuppressed(keys),
        })
    }

    public clear(): void {
        this.lazyLoader.clear()
    }

    /** Pre-send check: is this recipient currently on the team's suppression list? */
    public async isSuppressed(teamId: number, email: string): Promise<boolean> {
        // Enforcement is gated: when off, the list never blocks a send (writes may still populate it).
        if (!this.enforceEnabled) {
            return false
        }
        const identifier = normalizeIdentifier(email)
        if (!identifier) {
            return false
        }
        try {
            const suppressed = (await this.lazyLoader.get(toKey(teamId, identifier))) ?? false
            if (suppressed) {
                cdpEmailSuppressionTotal.inc({ result: 'suppressed_hit' })
            }
            return suppressed
        } catch (error) {
            // Fail open: a lookup error must never block a legitimate send.
            logger.error('[EmailSuppression] Failed to check suppression', { teamId, error })
            return false
        }
    }

    /**
     * Record one or more soft (Transient) bounces. Increments each address's consecutive-bounce
     * counter and auto-suppresses it in the same statement once it reaches the threshold. Manual
     * entries keep their suppressed state untouched.
     */
    public async recordTransientBounces(teamId: number, emails: string[], diagnostic?: string): Promise<void> {
        if (!this.writeEnabled) {
            return
        }
        const identifiers = Array.from(new Set(emails.map(normalizeIdentifier).filter(Boolean)))
        if (identifiers.length === 0) {
            return
        }

        const diag = diagnostic ? diagnostic.slice(0, DIAGNOSTIC_MAX_LENGTH) : null
        const reason = `Auto-suppressed after ${this.threshold} consecutive soft bounces`

        // Build a single multi-row upsert. Params: teamId, reason, threshold, diag, then one
        // identifier per row.
        const valueClauses: string[] = []
        const params: (number | string | null)[] = [teamId, reason, this.threshold, diag]
        identifiers.forEach((identifier, i) => {
            const p = params.length + 1 + i
            // gen_random_uuid() for the id, mirroring RecipientsManagerService.optOut. First bounce
            // starts the count at 1 and only suppresses immediately if the threshold is 1.
            valueClauses.push(
                `(gen_random_uuid(), $1, $${p}, 'BOUNCE', NULL, 1, NOW(), $4, (1 >= $3), CASE WHEN 1 >= $3 THEN NOW() ELSE NULL END, false, NOW(), NOW())`
            )
        })
        params.push(...identifiers)

        const query = `
            INSERT INTO posthog_messagesuppression
                (id, team_id, identifier, source, reason, transient_bounce_count, last_bounce_at,
                 last_bounce_diagnostic, suppressed, suppressed_at, deleted, created_at, updated_at)
            VALUES ${valueClauses.join(', ')}
            ON CONFLICT (team_id, identifier) DO UPDATE SET
                transient_bounce_count = posthog_messagesuppression.transient_bounce_count + 1,
                last_bounce_at = NOW(),
                last_bounce_diagnostic = EXCLUDED.last_bounce_diagnostic,
                -- Never downgrade or re-key a manual entry; only auto (BOUNCE) rows can cross the threshold.
                suppressed = CASE
                    WHEN posthog_messagesuppression.source = 'MANUAL' THEN posthog_messagesuppression.suppressed
                    WHEN posthog_messagesuppression.transient_bounce_count + 1 >= $3 THEN true
                    ELSE posthog_messagesuppression.suppressed END,
                suppressed_at = CASE
                    WHEN posthog_messagesuppression.source <> 'MANUAL'
                        AND posthog_messagesuppression.suppressed = false
                        AND posthog_messagesuppression.transient_bounce_count + 1 >= $3 THEN NOW()
                    ELSE posthog_messagesuppression.suppressed_at END,
                reason = CASE
                    WHEN posthog_messagesuppression.source <> 'MANUAL'
                        AND posthog_messagesuppression.transient_bounce_count + 1 >= $3 THEN $2
                    ELSE posthog_messagesuppression.reason END,
                -- A provably-undeliverable address coming back over threshold un-deletes itself.
                deleted = CASE
                    WHEN posthog_messagesuppression.source <> 'MANUAL'
                        AND posthog_messagesuppression.transient_bounce_count + 1 >= $3 THEN false
                    ELSE posthog_messagesuppression.deleted END,
                updated_at = NOW()
        `

        try {
            await this.postgres.query(PostgresUse.COMMON_WRITE, query, params, 'recordTransientBounces')
            cdpEmailSuppressionTotal.inc({ result: 'transient_bounce' }, identifiers.length)
            // Only invalidate the keys we touched — cross-team entries stay warm.
            this.lazyLoader.markForRefresh(identifiers.map((identifier) => toKey(teamId, identifier)))
        } catch (error) {
            logger.error('[EmailSuppression] Failed to record transient bounces', { teamId, error })
        }
    }

    /**
     * Record one or more hard (Permanent) bounces. Suppresses each address immediately — no
     * threshold, no counter — because a permanent bounce is definitive. Manual entries are never
     * touched. If a row already exists as an unsuppressed BOUNCE counter, this escalates it.
     */
    public async recordHardBounces(teamId: number, emails: string[], diagnostic?: string): Promise<void> {
        if (!this.writeEnabled) {
            return
        }
        const identifiers = Array.from(new Set(emails.map(normalizeIdentifier).filter(Boolean)))
        if (identifiers.length === 0) {
            return
        }

        const diag = diagnostic ? diagnostic.slice(0, DIAGNOSTIC_MAX_LENGTH) : null
        const reason = 'Auto-suppressed after a hard bounce'

        // Params: teamId, reason, diag, then one identifier per row.
        const valueClauses: string[] = []
        const params: (number | string | null)[] = [teamId, reason, diag]
        identifiers.forEach((identifier, i) => {
            const p = params.length + 1 + i
            valueClauses.push(
                `(gen_random_uuid(), $1, $${p}, 'BOUNCE', $2, 0, NOW(), $3, true, NOW(), false, NOW(), NOW())`
            )
        })
        params.push(...identifiers)

        const query = `
            INSERT INTO posthog_messagesuppression
                (id, team_id, identifier, source, reason, transient_bounce_count, last_bounce_at,
                 last_bounce_diagnostic, suppressed, suppressed_at, deleted, created_at, updated_at)
            VALUES ${valueClauses.join(', ')}
            ON CONFLICT (team_id, identifier) DO UPDATE SET
                last_bounce_at = NOW(),
                last_bounce_diagnostic = EXCLUDED.last_bounce_diagnostic,
                -- Manual entries are authoritative; never override them.
                suppressed = CASE
                    WHEN posthog_messagesuppression.source = 'MANUAL' THEN posthog_messagesuppression.suppressed
                    ELSE true END,
                suppressed_at = CASE
                    WHEN posthog_messagesuppression.source = 'MANUAL' THEN posthog_messagesuppression.suppressed_at
                    WHEN posthog_messagesuppression.suppressed = false THEN NOW()
                    ELSE posthog_messagesuppression.suppressed_at END,
                reason = CASE
                    WHEN posthog_messagesuppression.source = 'MANUAL' THEN posthog_messagesuppression.reason
                    ELSE EXCLUDED.reason END,
                -- A provably-undeliverable address coming back un-deletes itself.
                deleted = CASE
                    WHEN posthog_messagesuppression.source = 'MANUAL' THEN posthog_messagesuppression.deleted
                    ELSE false END,
                updated_at = NOW()
        `

        try {
            await this.postgres.query(PostgresUse.COMMON_WRITE, query, params, 'recordHardBounces')
            cdpEmailSuppressionTotal.inc({ result: 'hard_bounce' }, identifiers.length)
            // Only invalidate the keys we touched — cross-team entries stay warm.
            this.lazyLoader.markForRefresh(identifiers.map((identifier) => toKey(teamId, identifier)))
        } catch (error) {
            logger.error('[EmailSuppression] Failed to record hard bounces', { teamId, error })
        }
    }

    /**
     * Record successful deliveries. Resets the consecutive-bounce counter for auto (non-manual)
     * entries that haven't yet been suppressed, so a transient outage never accumulates.
     *
     * `deliveryTimestamp` guards against out-of-order events: SES delivery and bounce notifications
     * for different sends can arrive in any order, and a late delivery for an older send must not
     * erase a fresh bounce for a newer send. Reset only when the delivery is newer than the last
     * recorded bounce.
     */
    public async recordDeliveries(teamId: number, emails: string[], deliveryTimestamp?: string): Promise<void> {
        if (!this.writeEnabled) {
            return
        }
        const identifiers = Array.from(new Set(emails.map(normalizeIdentifier).filter(Boolean)))
        if (identifiers.length === 0) {
            return
        }

        // Fail closed on a missing delivery timestamp: without one we can't prove the delivery is
        // newer than the last bounce, so leave the counter alone rather than risk erasing a fresh
        // bounce. In practice the SES Delivery schema requires a timestamp, so this branch only
        // guards against a caller that forgets to pass it.
        const query = `
            UPDATE posthog_messagesuppression
            SET transient_bounce_count = 0, updated_at = NOW()
            WHERE team_id = $1
              AND identifier = ANY($2)
              AND source <> 'MANUAL'
              AND suppressed = false
              AND transient_bounce_count > 0
              AND (last_bounce_at IS NULL OR ($3::timestamptz IS NOT NULL AND last_bounce_at < $3::timestamptz))
        `
        try {
            await this.postgres.query(
                PostgresUse.COMMON_WRITE,
                query,
                [teamId, identifiers, deliveryTimestamp ?? null],
                'resetBounceCounts'
            )
        } catch (error) {
            logger.error('[EmailSuppression] Failed to reset bounce counts on delivery', { teamId, error })
        }
    }

    private async loadSuppressed(keys: string[]): Promise<Record<string, boolean>> {
        // keys are `${teamId}:${identifier}`. Identifiers may contain ':' only in exotic cases; the
        // stored identifier is an email so split on the first ':' only.
        const parsed = keys.map((key) => {
            const idx = key.indexOf(':')
            return { key, teamId: parseInt(key.slice(0, idx), 10), identifier: key.slice(idx + 1) }
        })

        // Group by team_id so we run one indexed `identifier = ANY(...)` scan per team instead of an
        // OR-chain of paired lookups. Same UNIQUE (team_id, identifier) index, cheaper plan and
        // prepared-statement reuse — matters when the LazyLoader coalesces many keys in a batch.
        // In practice most batches are single-team (one workflow, one team), so this is almost
        // always a single query regardless of batch size.
        const byTeam = new Map<number, string[]>()
        for (const p of parsed) {
            const list = byTeam.get(p.teamId) ?? []
            list.push(p.identifier)
            byTeam.set(p.teamId, list)
        }

        const suppressedKeys = new Set<string>()
        for (const [teamId, identifiers] of byTeam) {
            const result = await this.postgres.query<{ identifier: string }>(
                PostgresUse.COMMON_READ,
                `SELECT identifier
                 FROM posthog_messagesuppression
                 WHERE team_id = $1
                   AND identifier = ANY($2)
                   AND suppressed = true
                   AND deleted = false`,
                [teamId, identifiers],
                'loadSuppressed'
            )
            for (const row of result.rows) {
                suppressedKeys.add(toKey(teamId, row.identifier))
            }
        }

        // Default every requested key to false so the LazyLoader caches negatives too.
        return Object.fromEntries(parsed.map((p) => [p.key, suppressedKeys.has(p.key)]))
    }
}
