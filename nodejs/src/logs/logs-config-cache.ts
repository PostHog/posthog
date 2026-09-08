import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'

export const DEFAULT_LOGS_PATTERN_MESSAGE_KEYS: readonly string[] = Object.freeze(['message', 'msg', 'event'])

const REFRESH_MS = 30_000

type CacheEntry = {
    patternMessageKeys: readonly string[]
    fetchedAtMs: number
}

export class LogsConfigCache {
    private cache = new Map<number, CacheEntry>()
    private inFlight = new Map<number, Promise<readonly string[]>>()

    constructor(private postgres: PostgresRouter) {}

    public async getPatternMessageKeys(teamId: number): Promise<readonly string[]> {
        const existing = this.cache.get(teamId)
        if (existing && Date.now() - existing.fetchedAtMs < REFRESH_MS) {
            return existing.patternMessageKeys
        }
        const pending = this.inFlight.get(teamId)
        if (pending) {
            return pending
        }
        const refresh = this.refreshPatternMessageKeys(teamId)
        this.inFlight.set(teamId, refresh)
        try {
            return await refresh
        } finally {
            this.inFlight.delete(teamId)
        }
    }

    private async refreshPatternMessageKeys(teamId: number): Promise<readonly string[]> {
        let keys: readonly string[]
        try {
            keys = await this.fetchPatternMessageKeys(teamId)
        } catch (error) {
            logger.warn('[logs-config] fetch failed — falling back', { teamId, error: String(error) })
            keys = this.cache.get(teamId)?.patternMessageKeys ?? DEFAULT_LOGS_PATTERN_MESSAGE_KEYS
        }
        this.cache.set(teamId, { patternMessageKeys: keys, fetchedAtMs: Date.now() })
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
        return res.rows[0]?.logs_pattern_message_keys ?? DEFAULT_LOGS_PATTERN_MESSAGE_KEYS
    }
}
