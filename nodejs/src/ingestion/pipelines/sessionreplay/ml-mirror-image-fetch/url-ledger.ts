import { Redis } from 'ioredis'

import { RedisPool } from '~/types'

/**
 * What happened the last time this lane handled a URL.
 *
 * Every value except `seen` is the result of a request. `seen` is the dry-run outcome: it records
 * that the lane reached a URL and decided it would fetch it, without any request going out.
 *
 * That difference is load-bearing for whoever adds fetching. Deduping the measurement is a question
 * about whether this lane has handled a URL before, and any entry answers it. Skipping a request is
 * a question about whether a request already happened, and `seen` must answer that one with no. A
 * lane that treats `seen` as a completed fetch silently never downloads any URL the dry run reached.
 */
export type LedgerOutcome = 'ok' | 'not_found' | 'forbidden' | 'too_large' | 'not_image' | 'blocked' | 'error' | 'seen'

export interface LedgerEntry {
    fetchedAtMs: number
    outcome: LedgerOutcome
    etag?: string
    lastModified?: string
    expiresAtMs?: number
}

const KEY_PREFIX = 'imgfetch'

/**
 * A URL the dry run has already reached stays known for this long.
 *
 * Long enough that the key count converges on the distinct-URL count of the window, which is the
 * number that sizes the Redis. Short enough that the ledger cannot outlive the phase that filled it.
 */
export const SEEN_TTL_SECONDS = 30 * 24 * 60 * 60

export function ledgerKey(pseudoTeam: string, urlHash: string): string {
    return `${KEY_PREFIX}:${pseudoTeam}:${urlHash}`
}

function parseEntry(raw: Record<string, string>): LedgerEntry | null {
    const fetchedAtMs = Number(raw.fetchedAtMs)
    if (!raw.outcome || !Number.isFinite(fetchedAtMs)) {
        return null
    }
    return {
        fetchedAtMs,
        outcome: raw.outcome as LedgerOutcome,
        ...(raw.etag ? { etag: raw.etag } : {}),
        ...(raw.lastModified ? { lastModified: raw.lastModified } : {}),
        ...(raw.expiresAtMs ? { expiresAtMs: Number(raw.expiresAtMs) } : {}),
    }
}

/**
 * The record of which image URLs this lane has already reached, shared by every pod.
 *
 * The in-memory cache in front of it holds only what one pod saw since it started, so a rebalance or
 * a restart would otherwise send every URL out again. Losing this store costs outbound requests and
 * never costs correctness, which is why it is sized and evicted independently of the replay lane.
 */
export class UrlLedger {
    constructor(
        private readonly pool: RedisPool,
        private readonly commandTimeoutMs: number
    ) {}

    /** Entries for the keys that exist, in the order asked for, with a null where nothing is stored. */
    public async getMany(keys: string[]): Promise<(LedgerEntry | null)[]> {
        if (keys.length === 0) {
            return []
        }
        return this.withClient(async (client) => {
            const pipeline = client.pipeline()
            for (const key of keys) {
                pipeline.hgetall(key)
            }
            const results = await pipeline.exec()
            return keys.map((_key, index) => {
                const [error, value] = results?.[index] ?? [new Error('missing pipeline result'), null]
                if (error || !value || Object.keys(value as Record<string, string>).length === 0) {
                    return null
                }
                return parseEntry(value as Record<string, string>)
            })
        })
    }

    public async recordMany(entries: { key: string; entry: LedgerEntry; ttlSeconds: number }[]): Promise<void> {
        if (entries.length === 0) {
            return
        }
        await this.withClient(async (client) => {
            const pipeline = client.pipeline()
            for (const { key, entry, ttlSeconds } of entries) {
                const fields: Record<string, string> = {
                    fetchedAtMs: String(entry.fetchedAtMs),
                    outcome: entry.outcome,
                }
                if (entry.etag) {
                    fields.etag = entry.etag
                }
                if (entry.lastModified) {
                    fields.lastModified = entry.lastModified
                }
                if (entry.expiresAtMs !== undefined) {
                    fields.expiresAtMs = String(entry.expiresAtMs)
                }
                pipeline.hset(key, fields)
                pipeline.expire(key, ttlSeconds)
            }
            await pipeline.exec()
        })
    }

    private async withClient<T>(run: (client: Redis) => Promise<T>): Promise<T> {
        const client = await this.pool.acquire()
        try {
            return await Promise.race([
                run(client),
                new Promise<never>((_resolve, reject) =>
                    setTimeout(() => reject(new Error('url ledger command timed out')), this.commandTimeoutMs).unref()
                ),
            ])
        } finally {
            await this.pool.release(client)
        }
    }
}
