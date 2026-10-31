import { trace } from '@opentelemetry/api'

import { instrumentFn } from '~/common/tracing/tracing-utils'
import { DependencyUnavailableError } from '~/common/utils/db/error'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'

import { MESSAGE_KEYS } from './log-pattern-mask'

const REFRESH_MS = 30_000
const FAILED_REFRESH_RETRY_MS = 5_000

type CacheEntry = {
    messageKeys: readonly string[]
    expiresAtMs: number
}

const patternMessageKeysInstrumentOpts = { measureTime: false, sendException: false } as const

export class PatternMessageKeysCache {
    private cache = new Map<number, CacheEntry>()
    private inflight = new Map<number, Promise<readonly string[]>>()

    constructor(private postgres: PostgresRouter) {}

    public async getMessageKeys(teamId: number): Promise<readonly string[]> {
        return instrumentFn(
            {
                key: 'logsIngestion.patterns.getMessageKeys',
                ...patternMessageKeysInstrumentOpts,
                getLoggingContext: () => ({ team_id: teamId }),
            },
            async () => {
                const existing = this.cache.get(teamId)
                if (existing && Date.now() < existing.expiresAtMs) {
                    trace.getActiveSpan()?.setAttributes({ 'logs.patterns.message_keys_cache_hit': true })
                    return existing.messageKeys
                }

                // Messages are processed concurrently, so share one refresh per team.
                let refresh = this.inflight.get(teamId)
                if (!refresh) {
                    refresh = this.refresh(teamId, existing).finally(() => this.inflight.delete(teamId))
                    this.inflight.set(teamId, refresh)
                }
                return refresh
            }
        )
    }

    private async refresh(teamId: number, existing: CacheEntry | undefined): Promise<readonly string[]> {
        let messageKeys: readonly string[]
        try {
            messageKeys = await this.fetchMessageKeys(teamId)
        } catch (error) {
            if (!existing && error instanceof DependencyUnavailableError) {
                throw error
            }
            logger.warn('[logs-patterns] message keys fetch failed — falling back', {
                teamId,
                error: String(error),
            })
            trace.getActiveSpan()?.setAttributes({
                'logs.patterns.message_keys_fetch_failed': true,
                'logs.patterns.message_keys_served_stale': Boolean(existing),
            })
            const fallback = existing?.messageKeys ?? MESSAGE_KEYS
            // Hold the fallback briefly so a down database is not queried on every message.
            this.cache.set(teamId, { messageKeys: fallback, expiresAtMs: Date.now() + FAILED_REFRESH_RETRY_MS })
            return fallback
        }

        this.cache.set(teamId, { messageKeys, expiresAtMs: Date.now() + REFRESH_MS })
        trace.getActiveSpan()?.setAttributes({
            'logs.patterns.message_keys_cache_hit': false,
            'logs.patterns.message_keys_count': messageKeys.length,
        })
        return messageKeys
    }

    private async fetchMessageKeys(teamId: number): Promise<readonly string[]> {
        const res = await this.postgres.query<{ logs_pattern_message_keys: unknown }>(
            PostgresUse.COMMON_READ,
            `SELECT logs_pattern_message_keys FROM logs_teamlogsconfig WHERE team_id = $1`,
            [teamId],
            'logs-pattern-message-keys-fetch'
        )
        // A team that never opened logs settings has no row yet.
        const stored = res.rows[0]?.logs_pattern_message_keys
        if (!Array.isArray(stored) || !stored.every((key) => typeof key === 'string')) {
            return MESSAGE_KEYS
        }
        return stored
    }
}
