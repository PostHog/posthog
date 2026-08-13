import { Pool } from 'generic-pool'

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
const MAX_KEYS_PER_ROUND_TRIP = 256

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
    /** Keys whose read did not complete, which the caller must treat as unknown rather than as absent. */
    failed: number
}

/**
 * The two commands this store issues. Narrower than `Redis` so a test supplies exactly these, and a
 * command added here has to be added to the fake before it compiles.
 */
export interface SightingRedis {
    mget(...keys: string[]): Promise<(string | null)[]>
    pipeline(): {
        set(key: string, value: string, expiryMode: 'EX', seconds: number): unknown
        exec(): Promise<[Error | null, unknown][] | null>
    }
}

/** The three pool operations this store uses. Narrow so a test needs no cast to supply them. */
export type SightingRedisPool = Pick<Pool<SightingRedis>, 'acquire' | 'release' | 'destroy'>

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
 *
 * Both methods stop early once the batch budget is spent and report the rest as failed. A batch that
 * runs past Kafka's max.poll.interval.ms gets the pod evicted mid-batch, and the partition is then
 * replayed by a pod that will take just as long, so offered load rises while throughput falls.
 */
export class UrlSightings implements SightingStore {
    constructor(
        private readonly pool: SightingRedisPool,
        private readonly commandTimeoutMs: number,
        private readonly batchBudgetMs: number
    ) {}

    public async read(keys: string[]): Promise<SightingReadResult> {
        const known = new Set<number>()
        let failed = 0
        await this.forEachChunk(keys, {
            onChunk: async (client, batch, base) => {
                const values = await client.mget(...batch)
                values.forEach((value, index) => {
                    if (value !== null) {
                        known.add(base + index)
                    }
                })
            },
            onChunkFailed: (batch) => {
                failed += batch.length
            },
        })
        return { known, failed }
    }

    public async record(keys: string[], nowMs: number, ttlSeconds: number): Promise<{ failed: Set<number> }> {
        const failed = new Set<number>()
        const value = JSON.stringify({ seenAtMs: nowMs })
        await this.forEachChunk(keys, {
            onChunk: async (client, batch, base) => {
                const pipeline = client.pipeline()
                for (const key of batch) {
                    // One command, so a key can never be left without its expiry. A separate EXPIRE
                    // can be the command that fails, and the key it leaves behind is never reclaimed.
                    pipeline.set(key, value, 'EX', ttlSeconds)
                }
                const results = (await pipeline.exec()) as [Error | null, unknown][] | null
                batch.forEach((_key, index) => {
                    const result = results?.[index]
                    if (!result || result[0]) {
                        failed.add(base + index)
                    }
                })
            },
            onChunkFailed: (batch, base) => {
                batch.forEach((_key, index) => failed.add(base + index))
            },
        })
        return { failed }
    }

    private async forEachChunk(
        keys: string[],
        handlers: {
            onChunk: (client: SightingRedis, batch: string[], base: number) => Promise<void>
            onChunkFailed: (batch: string[], base: number) => void
        }
    ): Promise<void> {
        const startedAt = process.hrtime.bigint()
        const spentMs = (): number => Number(process.hrtime.bigint() - startedAt) / 1e6
        let base = 0
        for (const batch of chunk(keys, MAX_KEYS_PER_ROUND_TRIP)) {
            const at = base
            base += batch.length
            if (spentMs() > this.batchBudgetMs) {
                handlers.onChunkFailed(batch, at)
                continue
            }
            try {
                await this.withClient((client) => handlers.onChunk(client, batch, at))
            } catch {
                handlers.onChunkFailed(batch, at)
            }
        }
    }

    /**
     * The pool rejects rather than queues once its own acquire timeout passes, so this never races
     * `acquire()`. generic-pool cannot cancel one, and a caller that walked away from a pending
     * acquire is still handed the next free connection and still counted as borrowing it.
     *
     * A connection whose command was abandoned is destroyed rather than returned, because its reply
     * is still in flight and would be read as the answer to whichever command borrowed it next.
     */
    private async withClient(run: (client: SightingRedis) => Promise<void>): Promise<void> {
        const client = await this.pool.acquire()
        let timer: NodeJS.Timeout | undefined
        try {
            await Promise.race([
                run(client),
                new Promise<never>((_resolve, reject) => {
                    timer = setTimeout(
                        () => reject(new Error('sighting store command timed out')),
                        this.commandTimeoutMs
                    )
                    timer.unref()
                }),
            ])
        } catch (error) {
            await this.pool.destroy(client).catch(() => undefined)
            throw error
        } finally {
            clearTimeout(timer)
        }
        await this.pool.release(client)
    }
}
