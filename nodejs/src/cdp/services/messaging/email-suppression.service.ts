import { createHash } from 'crypto'
import { Counter } from 'prom-client'

import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'
import { logger } from '~/common/utils/logger'
import { isValidTeamId } from '~/common/utils/team-manager'

const cdpEmailSuppressionTotal = new Counter({
    name: 'cdp_email_suppression_total',
    help: 'Email suppression-list outcomes. `suppressed_hit` = a send skipped because the recipient is on the list; `transient_bounce` = a soft-bounce counter increment; `hard_bounce` = an address suppressed immediately after a permanent bounce; `complaint` = an address suppressed immediately after a spam complaint; `known_invalid_recorded` = an address added to the cross-team known-invalid list; `known_invalid_cleared` = an address removed from that list after a delivery; `known_invalid_hit` = a send skipped because of that list; `known_invalid_shadow_hit` = a send that list would skip in shadow mode.',
    labelNames: ['result'],
})

const DIAGNOSTIC_MAX_LENGTH = 1000

const normalizeIdentifier = (email: string): string => email.trim().toLowerCase()

const toKey = (teamId: number, identifier: string): string => `${teamId}:${identifier}`

// The known-invalid list stores a hash, so a raw address never leaves the team that emailed it.
// Django's admin computes the same hash to search the list.
const hashIdentifier = (identifier: string): string => createHash('sha256').update(identifier).digest('hex')

export type KnownInvalidMode = 'off' | 'shadow' | 'enforce'

export function parseKnownInvalidMode(value: string | undefined): KnownInvalidMode {
    const mode = (value ?? '').trim().toLowerCase()
    return mode === 'shadow' || mode === 'enforce' ? mode : 'off'
}

export type EmailSuppressionConfig = {
    // Consecutive soft bounces before auto-suppression.
    transientBounceThreshold: number
    // How the cross-team known-invalid list acts. See EMAIL_SUPPRESSION_KNOWN_INVALID_MODE.
    knownInvalidMode?: KnownInvalidMode
    // Days a known-invalid entry keeps blocking sends after its last bounce.
    knownInvalidTtlDays?: number
}

// Test helper — production paths take config from `CdpConfig`; tests that still mutate process.env
// can call this to construct the same shape without duplicating the parse logic.
export function emailSuppressionConfigFromEnv(): EmailSuppressionConfig {
    const rawThreshold = process.env.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD
    const parsedThreshold = rawThreshold ? parseInt(rawThreshold, 10) : NaN
    return {
        transientBounceThreshold: Number.isFinite(parsedThreshold) && parsedThreshold > 0 ? parsedThreshold : 5,
    }
}

export type SuppressionCheckOptions = {
    // Transactional email (invoices, login codes, password resets) is blocked only by a hard bounce, because
    // only then is the address proven dead. A complaint, a manual entry or a full inbox (soft bounces) lets it through.
    transactional?: boolean
}

// An active suppression. It blocks transactional email only when the address hard-bounced. `knownInvalid`
// marks an entry that only the cross-team known-invalid list holds: in shadow mode it is counted, not enforced.
type SuppressionEntry = { blocksTransactional: boolean; knownInvalid?: 'shadow' | 'enforce' }

const HARD_BOUNCE_REASON = 'Auto-suppressed after a hard bounce'
const KNOWN_INVALID_REASON = "This address doesn't exist. Emails to it bounced before."

// Reasons that mark a dead address on rows written before `hard_bounced_at` existed: our own hard-bounce
// rows, and the two Customer.io lists the importer maps to BOUNCE. Both writers now set the column, so
// this list is closed and only covers rows already on disk.
const LEGACY_HARD_BOUNCE_REASONS = [
    HARD_BOUNCE_REASON,
    'Imported from Customer.io (bounced)',
    'Imported from Customer.io (invalid address)',
]

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
 * `recordHardBounces` and `recordComplaints` suppress an address immediately — a permanent bounce
 * or a spam complaint is definitive. Manual entries (added via the API/UI) are never touched by
 * any of this bookkeeping.
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
    private readonly knownInvalidMode: KnownInvalidMode
    private readonly knownInvalidTtlDays: number
    // A key's active suppression, or false when it has none.
    private readonly lazyLoader: LazyLoader<SuppressionEntry | false>

    constructor(
        private postgres: PostgresRouter,
        config: EmailSuppressionConfig
    ) {
        this.threshold = config.transientBounceThreshold
        this.knownInvalidMode = config.knownInvalidMode ?? 'off'
        this.knownInvalidTtlDays = config.knownInvalidTtlDays ?? 180
        this.lazyLoader = new LazyLoader<SuppressionEntry | false>({
            name: 'email_suppression',
            loader: async (keys) => await this.loadSuppressed(keys),
        })
    }

    public clear(): void {
        this.lazyLoader.clear()
    }

    /** Pre-send check: does the team's suppression list block this recipient for this kind of email? */
    public async isSuppressed(
        teamId: number,
        email: string,
        { transactional = false }: SuppressionCheckOptions = {}
    ): Promise<boolean> {
        const identifier = normalizeIdentifier(email)
        if (!identifier) {
            return false
        }
        try {
            const entry = (await this.lazyLoader.get(toKey(teamId, identifier))) ?? false
            if (entry !== false && entry.knownInvalid === 'shadow') {
                cdpEmailSuppressionTotal.inc({ result: 'known_invalid_shadow_hit' })
                return false
            }
            const suppressed = entry !== false && (!transactional || entry.blocksTransactional)
            if (suppressed) {
                cdpEmailSuppressionTotal.inc({ result: entry.knownInvalid ? 'known_invalid_hit' : 'suppressed_hit' })
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
     * entries keep their suppressed state untouched, and complaint entries keep their reason.
     */
    public async recordTransientBounces(teamId: number, emails: string[], diagnostic?: string): Promise<void> {
        const identifiers = Array.from(new Set(emails.map(normalizeIdentifier).filter(Boolean)))
        if (identifiers.length === 0) {
            return
        }

        const diag = diagnostic ? diagnostic.slice(0, DIAGNOSTIC_MAX_LENGTH) : null
        const reason = `Auto-suppressed after ${this.threshold} consecutive soft bounces`

        // Build a single multi-row upsert. Params: teamId, reason, threshold, diag, legacy reasons,
        // then one identifier per row.
        const valueClauses: string[] = []
        const params: (number | string | string[] | null)[] = [
            teamId,
            reason,
            this.threshold,
            diag,
            LEGACY_HARD_BOUNCE_REASONS,
        ]
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
                -- Same precedence as the hard-bounce path: a COMPLAINT row keeps its reason so it
                -- can't end up labelled COMPLAINT while reading as a soft-bounce suppression.
                reason = CASE
                    WHEN posthog_messagesuppression.source NOT IN ('MANUAL', 'COMPLAINT')
                        AND posthog_messagesuppression.transient_bounce_count + 1 >= $3 THEN $2
                    ELSE posthog_messagesuppression.reason END,
                -- The reason update above replaces the text that an older row carries its hard-bounce
                -- mark in. Move the mark to the column first, so the row keeps blocking transactional email.
                hard_bounced_at = COALESCE(
                    posthog_messagesuppression.hard_bounced_at,
                    CASE WHEN posthog_messagesuppression.source = 'BOUNCE'
                              AND posthog_messagesuppression.reason = ANY($5) THEN NOW() END),
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
     * touched. If a row already exists as an unsuppressed BOUNCE counter, this escalates it. A row
     * that a complaint already claimed keeps its source and reason, so the bounce refreshes the
     * diagnostic without relabelling why the address is suppressed.
     */
    public async recordHardBounces(teamId: number, emails: string[], diagnostic?: string): Promise<void> {
        const identifiers = Array.from(new Set(emails.map(normalizeIdentifier).filter(Boolean)))
        if (identifiers.length === 0) {
            return
        }

        const diag = diagnostic ? diagnostic.slice(0, DIAGNOSTIC_MAX_LENGTH) : null
        // Params: teamId, reason, diag, then one identifier per row.
        const valueClauses: string[] = []
        const params: (number | string | null)[] = [teamId, HARD_BOUNCE_REASON, diag]
        identifiers.forEach((identifier, i) => {
            const p = params.length + 1 + i
            valueClauses.push(
                `(gen_random_uuid(), $1, $${p}, 'BOUNCE', $2, 0, NOW(), $3, true, NOW(), false, NOW(), NOW(), NOW())`
            )
        })
        params.push(...identifiers)

        const query = `
            INSERT INTO posthog_messagesuppression
                (id, team_id, identifier, source, reason, transient_bounce_count, last_bounce_at,
                 last_bounce_diagnostic, suppressed, suppressed_at, deleted, created_at, updated_at,
                 hard_bounced_at)
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
                -- Set on every row, manual and complaint entries included: the address can't receive
                -- mail, so transactional email must stop too.
                hard_bounced_at = NOW(),
                -- A complaint outranks a bounce as the reason a row exists, so it keeps its reason
                -- here the way a manual entry does. This upsert never reassigns the source, so
                -- overwriting the reason on a COMPLAINT row would leave the two contradicting each
                -- other. The bounce still refreshes the diagnostic and the suppression state above.
                reason = CASE
                    WHEN posthog_messagesuppression.source IN ('MANUAL', 'COMPLAINT') THEN posthog_messagesuppression.reason
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
     * Add addresses to the cross-team known-invalid list. Call this only for a hard bounce that proves
     * the address does not exist. A bounce caused by the sender, such as a blocked domain, must stay on
     * the team's own list, or one team's sending problem would block the address for every team.
     */
    public async recordKnownInvalid(teamId: number, emails: string[]): Promise<void> {
        if (this.knownInvalidMode === 'off') {
            return
        }
        const hashes = Array.from(new Set(emails.map(normalizeIdentifier).filter(Boolean))).map(hashIdentifier)
        if (hashes.length === 0) {
            return
        }

        // Params: teamId, then one hash per row.
        const valueClauses = hashes.map((_, i) => `($${i + 2}, NOW(), NOW(), $1)`)
        const query = `
            INSERT INTO posthog_knowninvalidemailaddress
                (identifier_hash, first_bounced_at, last_bounced_at, last_bounced_team_id)
            VALUES ${valueClauses.join(', ')}
            ON CONFLICT (identifier_hash) DO UPDATE SET
                last_bounced_at = NOW(),
                last_bounced_team_id = EXCLUDED.last_bounced_team_id
        `
        try {
            await this.postgres.query(PostgresUse.COMMON_WRITE, query, [teamId, ...hashes], 'recordKnownInvalid')
            cdpEmailSuppressionTotal.inc({ result: 'known_invalid_recorded' }, hashes.length)
        } catch (error) {
            logger.error('[EmailSuppression] Failed to record known-invalid addresses', { teamId, error })
        }
    }

    /**
     * Record one or more spam complaints. Suppresses each address immediately — no threshold —
     * because a complaint is the recipient asking us to stop, and provider complaint-rate
     * thresholds are far tighter than bounce thresholds. Manual entries are never touched; any
     * other existing row is re-keyed to COMPLAINT so the list shows the operative reason. The
     * bounce paths then treat COMPLAINT as authoritative, so a later bounce can't relabel the row.
     */
    public async recordComplaints(teamId: number, emails: string[], feedbackType?: string): Promise<void> {
        const identifiers = Array.from(new Set(emails.map(normalizeIdentifier).filter(Boolean)))
        if (identifiers.length === 0) {
            return
        }

        // The feedback type is the provider's classification of the report (e.g. "abuse",
        // "fraud"); surface it in the reason for operator visibility.
        const reason = feedbackType
            ? `Auto-suppressed after a spam complaint (feedback type: ${feedbackType.slice(0, 100)})`
            : 'Auto-suppressed after a spam complaint'

        // Params: teamId, reason, legacy reasons, then one identifier per row.
        const valueClauses: string[] = []
        const params: (number | string | string[] | null)[] = [teamId, reason, LEGACY_HARD_BOUNCE_REASONS]
        identifiers.forEach((identifier, i) => {
            const p = params.length + 1 + i
            valueClauses.push(
                `(gen_random_uuid(), $1, $${p}, 'COMPLAINT', $2, 0, NULL, NULL, true, NOW(), false, NOW(), NOW())`
            )
        })
        params.push(...identifiers)

        const query = `
            INSERT INTO posthog_messagesuppression
                (id, team_id, identifier, source, reason, transient_bounce_count, last_bounce_at,
                 last_bounce_diagnostic, suppressed, suppressed_at, deleted, created_at, updated_at)
            VALUES ${valueClauses.join(', ')}
            ON CONFLICT (team_id, identifier) DO UPDATE SET
                -- Manual entries are authoritative; never override them. Any other row re-keys to
                -- COMPLAINT: the complaint is the operative reason the address is suppressed now.
                source = CASE
                    WHEN posthog_messagesuppression.source = 'MANUAL' THEN posthog_messagesuppression.source
                    ELSE 'COMPLAINT' END,
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
                -- The reason update above replaces the text that an older row carries its hard-bounce
                -- mark in. Move the mark to the column first, so the row keeps blocking transactional email.
                hard_bounced_at = COALESCE(
                    posthog_messagesuppression.hard_bounced_at,
                    CASE WHEN posthog_messagesuppression.source = 'BOUNCE'
                              AND posthog_messagesuppression.reason = ANY($3) THEN NOW() END),
                -- A soft-deleted row comes back: the complaint is fresh evidence the recipient
                -- must not be mailed.
                deleted = CASE
                    WHEN posthog_messagesuppression.source = 'MANUAL' THEN posthog_messagesuppression.deleted
                    ELSE false END,
                updated_at = NOW()
        `

        try {
            await this.postgres.query(PostgresUse.COMMON_WRITE, query, params, 'recordComplaints')
            cdpEmailSuppressionTotal.inc({ result: 'complaint' }, identifiers.length)
            // Only invalidate the keys we touched — cross-team entries stay warm.
            this.lazyLoader.markForRefresh(identifiers.map((identifier) => toKey(teamId, identifier)))
        } catch (error) {
            logger.error('[EmailSuppression] Failed to record complaints', { teamId, error })
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
            this.lazyLoader.markForRefresh(identifiers.map((identifier) => toKey(teamId, identifier)))
        } catch (error) {
            logger.error('[EmailSuppression] Failed to reset bounce counts on delivery', { teamId, error })
        }

        if (this.knownInvalidMode === 'off') {
            return
        }
        // A delivery proves the address exists again, for example after a mailbox provider reused it.
        // The same timestamp guard applies: a late delivery for an older send must not clear a fresh bounce.
        try {
            const result = await this.postgres.query(
                PostgresUse.COMMON_WRITE,
                `DELETE FROM posthog_knowninvalidemailaddress
                 WHERE identifier_hash = ANY($1)
                   AND $2::timestamptz IS NOT NULL
                   AND last_bounced_at < $2::timestamptz`,
                [identifiers.map(hashIdentifier), deliveryTimestamp ?? null],
                'clearKnownInvalid'
            )
            if (result.rowCount) {
                cdpEmailSuppressionTotal.inc({ result: 'known_invalid_cleared' }, result.rowCount)
            }
        } catch (error) {
            logger.error('[EmailSuppression] Failed to clear known-invalid addresses on delivery', { teamId, error })
        }
    }

    private async loadSuppressed(keys: string[]): Promise<Record<string, SuppressionEntry | false>> {
        // keys are `${teamId}:${identifier}`. Identifiers may contain ':' only in exotic cases; the
        // stored identifier is an email so split on the first ':' only.
        const parsed = keys.map((key) => {
            const idx = key.indexOf(':')
            return { key, teamId: Number(key.slice(0, idx)), identifier: key.slice(idx + 1) }
        })

        // Group by team_id so we run one indexed `identifier = ANY(...)` scan per team instead of an
        // OR-chain of paired lookups. Same UNIQUE (team_id, identifier) index, cheaper plan and
        // prepared-statement reuse — matters when the LazyLoader coalesces many keys in a batch.
        // In practice most batches are single-team (one workflow, one team), so this is almost
        // always a single query regardless of batch size.
        const byTeam = new Map<number, string[]>()
        for (const p of parsed) {
            if (!isValidTeamId(p.teamId)) {
                continue
            }
            const list = byTeam.get(p.teamId) ?? []
            list.push(p.identifier)
            byTeam.set(p.teamId, list)
        }

        const entries = new Map<string, SuppressionEntry>()
        // Keys the team's own list neither suppresses nor allows. Only these can hit the known-invalid list.
        const unlisted: { key: string; teamId: number; identifier: string }[] = []
        for (const [teamId, identifiers] of byTeam) {
            // The reason check covers rows that hard-bounced before `hard_bounced_at` existed.
            const result = await this.postgres.query<{
                identifier: string
                active: boolean
                known_invalid_allowed: boolean
                blocks_transactional: boolean
            }>(
                PostgresUse.COMMON_READ,
                `SELECT identifier,
                        (suppressed AND NOT deleted) AS active,
                        known_invalid_allowed_at IS NOT NULL AS known_invalid_allowed,
                        -- A soft-bounce row carries no reason until it crosses the threshold, and
                        -- NULL = ANY(...) is NULL, so COALESCE keeps the column a real boolean.
                        COALESCE(
                            hard_bounced_at IS NOT NULL
                                OR source = 'KNOWN_INVALID'
                                OR (source = 'BOUNCE' AND reason = ANY($3)),
                            false
                        ) AS blocks_transactional
                 FROM posthog_messagesuppression
                 WHERE team_id = $1
                   AND identifier = ANY($2)
                   AND ((suppressed = true AND deleted = false) OR known_invalid_allowed_at IS NOT NULL)`,
                [teamId, identifiers, LEGACY_HARD_BOUNCE_REASONS],
                'loadSuppressed'
            )
            const listed = new Set<string>()
            for (const row of result.rows) {
                listed.add(row.identifier)
                if (row.active) {
                    entries.set(toKey(teamId, row.identifier), { blocksTransactional: row.blocks_transactional })
                }
            }
            for (const identifier of identifiers) {
                if (!listed.has(identifier)) {
                    unlisted.push({ key: toKey(teamId, identifier), teamId, identifier })
                }
            }
        }

        if (this.knownInvalidMode !== 'off' && unlisted.length > 0) {
            await this.applyKnownInvalid(unlisted, entries)
        }

        // Default every requested key to false so the LazyLoader caches negatives too.
        return Object.fromEntries(parsed.map((p) => [p.key, entries.get(p.key) ?? false]))
    }

    private async applyKnownInvalid(
        unlisted: { key: string; teamId: number; identifier: string }[],
        entries: Map<string, SuppressionEntry>
    ): Promise<void> {
        let invalidHashes: Set<string>
        try {
            const result = await this.postgres.query<{ identifier_hash: string }>(
                PostgresUse.COMMON_READ,
                `SELECT identifier_hash
                 FROM posthog_knowninvalidemailaddress
                 WHERE identifier_hash = ANY($1)
                   AND last_bounced_at > NOW() - make_interval(days => $2)`,
                [Array.from(new Set(unlisted.map((u) => hashIdentifier(u.identifier)))), this.knownInvalidTtlDays],
                'loadKnownInvalid'
            )
            invalidHashes = new Set(result.rows.map((row) => row.identifier_hash))
        } catch (error) {
            // Fail open, like the rest of the pre-send check, but keep the team's own list.
            logger.error('[EmailSuppression] Failed to check known-invalid addresses', { error })
            return
        }

        const hitsByTeam = new Map<number, string[]>()
        for (const { key, teamId, identifier } of unlisted) {
            if (!invalidHashes.has(hashIdentifier(identifier))) {
                continue
            }
            if (this.knownInvalidMode === 'shadow') {
                entries.set(key, { blocksTransactional: false, knownInvalid: 'shadow' })
                continue
            }
            // The address does not exist, so transactional email can't reach it either.
            entries.set(key, { blocksTransactional: true, knownInvalid: 'enforce' })
            hitsByTeam.set(teamId, [...(hitsByTeam.get(teamId) ?? []), identifier])
        }

        for (const [teamId, identifiers] of hitsByTeam) {
            await this.addKnownInvalidRows(teamId, identifiers)
        }
    }

    /**
     * Add a KNOWN_INVALID row to the team's own list for each address the known-invalid list blocked.
     * The team then sees the address on its suppression list, and can remove it there. Other teams'
     * entries are never listed, so a team only sees addresses it tried to email.
     */
    private async addKnownInvalidRows(teamId: number, identifiers: string[]): Promise<void> {
        // Params: teamId, reason, then one identifier per row.
        const valueClauses = identifiers.map(
            (_, i) =>
                `(gen_random_uuid(), $1, $${i + 3}, 'KNOWN_INVALID', $2, 0, NULL, NULL, true, NOW(), false, NOW(), NOW())`
        )
        // The WHERE clause re-checks what the read saw, because a user can remove the address or a
        // bounce can suppress it between the read and this write.
        const query = `
            INSERT INTO posthog_messagesuppression
                (id, team_id, identifier, source, reason, transient_bounce_count, last_bounce_at,
                 last_bounce_diagnostic, suppressed, suppressed_at, deleted, created_at, updated_at)
            VALUES ${valueClauses.join(', ')}
            ON CONFLICT (team_id, identifier) DO UPDATE SET
                source = 'KNOWN_INVALID',
                reason = EXCLUDED.reason,
                suppressed = true,
                suppressed_at = NOW(),
                deleted = false,
                updated_at = NOW()
            WHERE posthog_messagesuppression.known_invalid_allowed_at IS NULL
              AND posthog_messagesuppression.source <> 'MANUAL'
              AND NOT (posthog_messagesuppression.suppressed AND NOT posthog_messagesuppression.deleted)
        `
        try {
            await this.postgres.query(
                PostgresUse.COMMON_WRITE,
                query,
                [teamId, KNOWN_INVALID_REASON, ...identifiers],
                'addKnownInvalidRows'
            )
        } catch (error) {
            logger.error('[EmailSuppression] Failed to add known-invalid rows', { teamId, error })
        }
    }
}
