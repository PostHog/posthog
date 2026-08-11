import { Redis } from 'ioredis'

import { RedisPool } from '~/types'

/**
 * The dry run records sightings under their own prefix, separate from the fetch results a later
 * lane will write.
 *
 * Two stores rather than one outcome value, because they answer different questions and only one of
 * them may suppress a request. A sighting says this lane has handled a URL, which is what the phase
 * 0 dedup measurement counts. It says nothing about bytes, because none were downloaded. Sharing a
 * keyspace would leave whoever enables fetching with 30 days of entries that look like completed
 * work, and every URL behind them would be skipped with no error and no metric to show it.
 */
const SIGHTING_PREFIX = 'imgfetch:seen'

/**
 * Long enough that the key count converges on the distinct-URL count of the window, which is the
 * number that sizes the Redis. Short enough that sightings cannot outlive the phase that wrote them.
 */
export const SIGHTING_TTL_SECONDS = 30 * 24 * 60 * 60

/** Bounds one round trip. A poll batch can carry thousands of URLs, and one pipeline holding all of them times out as a unit. */
const MAX_COMMANDS_PER_PIPELINE = 256

export function sightingKey(pseudoTeam: string, urlHash: string): string {
    return `${SIGHTING_PREFIX}:${pseudoTeam}:${urlHash}`
}

function chunk<T>(items: T[], size: number): T[][] {
    const out: T[][] = []
    for (let i = 0; i < items.length; i += size) {
        out.push(items.slice(i, i + size))
    }
    return out
}

export interface SightingReadResult {
    /** Indexes of the keys that were already recorded. */
    known: Set<number>
    /** Keys whose read failed, which the caller must treat as unknown rather than as absent. */
    failed: number
}

/** What the consumer needs of the store, so its tests exercise the real contract rather than a cast. */
export interface SightingStore {
    read(keys: string[]): Promise<SightingReadResult>
    record(keys: string[], nowMs: number, ttlSeconds: number): Promise<{ failed: Set<number> }>
}

/**
 * The record of which image URLs this lane has already reached, shared by every pod.
 *
 * The in-memory cache in front of it holds only what one pod saw since it started, so a rebalance
 * or a restart would otherwise count every URL again. Losing this store costs an overstated
 * measurement now, and outbound requests once fetching is on. It never costs correctness.
 */
export class UrlSightings implements SightingStore {
    constructor(
        private readonly pool: RedisPool,
        private readonly commandTimeoutMs: number
    ) {}

    /**
     * A key whose read failed is reported as failed rather than as absent, because the two mean
     * opposite things to a caller deciding whether it has handled a URL before.
     */
    public async read(keys: string[]): Promise<SightingReadResult> {
        const known = new Set<number>()
        let failed = 0
        let offset = 0
        for (const batch of chunk(keys, MAX_COMMANDS_PER_PIPELINE)) {
            const base = offset
            offset += batch.length
            let results: [Error | null, unknown][] | null
            try {
                results = await this.withClient(async (client) => {
                    const pipeline = client.pipeline()
                    for (const key of batch) {
                        pipeline.get(key)
                    }
                    return (await pipeline.exec()) as [Error | null, unknown][] | null
                })
            } catch {
                failed += batch.length
                continue
            }
            for (let i = 0; i < batch.length; i++) {
                const entry = results?.[i]
                if (!entry || entry[0]) {
                    failed++
                } else if (entry[1] !== null && entry[1] !== undefined) {
                    known.add(base + i)
                }
            }
        }
        return { known, failed }
    }

    /** Returns how many keys could not be written, so the caller can decide what to un-mark. */
    public async record(keys: string[], nowMs: number, ttlSeconds: number): Promise<{ failed: Set<number> }> {
        const failed = new Set<number>()
        const value = JSON.stringify({ seenAtMs: nowMs })
        let offset = 0
        for (const batch of chunk(keys, MAX_COMMANDS_PER_PIPELINE)) {
            const base = offset
            offset += batch.length
            let results: [Error | null, unknown][] | null
            try {
                results = await this.withClient(async (client) => {
                    const pipeline = client.pipeline()
                    for (const key of batch) {
                        // One command, so a key can never be left without its expiry. A separate
                        // EXPIRE can be the command that fails, and the key it leaves behind has no
                        // TTL and is never reclaimed.
                        pipeline.set(key, value, 'EX', ttlSeconds)
                    }
                    return (await pipeline.exec()) as [Error | null, unknown][] | null
                })
            } catch {
                for (let i = 0; i < batch.length; i++) {
                    failed.add(base + i)
                }
                continue
            }
            for (let i = 0; i < batch.length; i++) {
                const entry = results?.[i]
                if (!entry || entry[0]) {
                    failed.add(base + i)
                }
            }
        }
        return { failed }
    }

    /**
     * The deadline covers acquiring a connection as well as the command, because an exhausted pool
     * blocks for as long as a stalled Redis does and both end at the poll loop. A connection whose
     * command was abandoned is destroyed rather than returned, since its reply is still in flight
     * and would be read as the answer to whichever command borrowed it next.
     */
    private async withClient<T>(run: (client: Redis) => Promise<T>): Promise<T> {
        let timer: NodeJS.Timeout | undefined
        const deadline = new Promise<never>((_resolve, reject) => {
            timer = setTimeout(() => reject(new Error('url sighting store timed out')), this.commandTimeoutMs)
            timer.unref()
        })
        let client: Redis | undefined
        try {
            client = await Promise.race([this.pool.acquire(), deadline])
            return await Promise.race([run(client), deadline])
        } catch (error) {
            if (client) {
                await this.pool.destroy(client).catch(() => undefined)
                client = undefined
            }
            throw error
        } finally {
            clearTimeout(timer)
            if (client) {
                await this.pool.release(client)
            }
        }
    }
}
