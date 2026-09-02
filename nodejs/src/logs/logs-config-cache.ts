import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'

const REFRESH_MS = 30_000

type CacheEntry = {
    patternMessageKeys: readonly string[]
    fetchedAtMs: number
}

/**
 * Per-team `TeamLogsConfig` row with a 30s TTL, mirroring `RetentionRulesCache`.
 *
 * A team with no row resolves to an empty key list, which turns message extraction off. The row is
 * created lazily on the first `logs_config` API read, so a team that never opened logs settings has
 * none. Extraction being off for that team is the intended reading of "no stored list".
 */
export class LogsConfigCache {
    private cache = new Map<number, CacheEntry>()

    constructor(private postgres: PostgresRouter) {}

    public async getPatternMessageKeys(teamId: number): Promise<readonly string[]> {
        const now = Date.now()
        const existing = this.cache.get(teamId)
        if (existing && now - existing.fetchedAtMs < REFRESH_MS) {
            return existing.patternMessageKeys
        }
        let keys: readonly string[]
        try {
            keys = await this.fetchPatternMessageKeys(teamId)
        } catch (error) {
            // Fail open: this runs in the ingestion hot path, so a fetch failure must never DLQ
            // otherwise-valid logs. Serve the last-known list when there is one; otherwise an empty
            // list, which masks without extraction. The stale `fetchedAtMs` retries on the next message.
            logger.warn('[logs-config] fetch failed — falling back', { teamId, error: String(error) })
            return existing?.patternMessageKeys ?? []
        }
        this.cache.set(teamId, { patternMessageKeys: keys, fetchedAtMs: now })
        return keys
    }

    private async fetchPatternMessageKeys(teamId: number): Promise<readonly string[]> {
        const res = await this.postgres.query<{ logs_pattern_message_keys: string[] | null }>(
            PostgresUse.COMMON_READ,
            `SELECT logs_pattern_message_keys
             FROM logs_teamlogsconfig
             WHERE team_id = $1`,
            [teamId],
            'logs-config-fetch'
        )
        return res.rows[0]?.logs_pattern_message_keys ?? []
    }
}
