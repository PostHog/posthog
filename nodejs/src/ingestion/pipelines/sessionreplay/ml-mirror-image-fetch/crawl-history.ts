import { Pool } from 'generic-pool'

/**
 * The keyspace of the URL-seen test, asked before every fetch. An entry means this lane finished
 * with the URL, whatever the outcome, so a URL the site refused sits beside one it served.
 *
 * The entry says nothing about the bytes, which live under their own keys once a later lane writes
 * them. One keyspace for both would leave whoever enables fetching with a month of entries that look
 * like completed downloads, and the lane would skip every URL behind them with no error.
 */
const CRAWL_HISTORY_PREFIX = 'imgfetch:seen'

/** Bounds one round trip. A poll batch can carry thousands of URLs, and one pipeline holding all of them times out as a unit. */
const MAX_KEYS_PER_ROUND_TRIP = 256

export function crawlHistoryKey(pseudoTeam: string, urlHash: string): string {
    return `${CRAWL_HISTORY_PREFIX}:${pseudoTeam}:${urlHash}`
}

function chunk<T>(items: T[], size: number): T[][] {
    const out: T[][] = []
    for (let i = 0; i < items.length; i += size) {
        out.push(items.slice(i, i + size))
    }
    return out
}

export interface CrawlHistoryReadResult {
    /** Indexes of the keys the store already holds. */
    known: Set<number>
    /** Indexes whose read did not complete. The caller knows nothing about these, which is not the same as knowing they are absent. */
    failed: Set<number>
}

/**
 * Narrower than `Redis`, so a test supplies exactly these commands, and a command added here must
 * reach the fake before this compiles.
 */
export interface CrawlHistoryRedis {
    mget(...keys: string[]): Promise<(string | null)[]>
    pipeline(): {
        set(key: string, value: string, expiryMode: 'EX', seconds: number): unknown
        exec(): Promise<[Error | null, unknown][] | null>
    }
}

/** Narrow, so a test supplies these operations without a cast. */
export type CrawlHistoryRedisPool = Pick<Pool<CrawlHistoryRedis>, 'acquire' | 'release' | 'destroy'>

/** What the consumer needs of the store, so its tests exercise the real contract rather than a cast. */
export interface CrawlHistoryStore {
    read(keys: string[], nowMs: number): Promise<CrawlHistoryReadResult>
    record(keys: string[], nowMs: number, ttlSeconds: number): Promise<{ failed: Set<number> }>
}

/**
 * Every pod shares this store. The in-memory cache in front of it holds only what one pod saw since
 * it started, so a rebalance or a restart would otherwise count every URL again. A lost store costs
 * an overstated measurement now, and outbound requests once fetching is on. It never costs
 * correctness.
 *
 * Both methods stop early once the batch budget is spent and report the rest as failed. Kafka evicts
 * a pod whose batch runs past max.poll.interval.ms, and the next pod replays that partition and
 * takes just as long, so offered load rises while throughput falls.
 */
export class CrawlHistory implements CrawlHistoryStore {
    constructor(
        private readonly pool: CrawlHistoryRedisPool,
        private readonly commandTimeoutMs: number,
        private readonly batchBudgetMs: number
    ) {}

    public async read(keys: string[], _nowMs: number): Promise<CrawlHistoryReadResult> {
        const known = new Set<number>()
        const failed = new Set<number>()
        await this.forEachChunk(keys, {
            onChunk: async (client, batch, base) => {
                const values = await client.mget(...batch)
                values.forEach((value, index) => {
                    if (value !== null) {
                        known.add(base + index)
                    }
                })
            },
            onChunkFailed: (batch, base) => {
                batch.forEach((_key, index) => failed.add(base + index))
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
                    // One command, so a key can never sit without its expiry. A separate EXPIRE can
                    // be the command that fails, and Redis never reclaims the key it leaves behind.
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
            onChunk: (client: CrawlHistoryRedis, batch: string[], base: number) => Promise<void>
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
     * `acquire()`. generic-pool cannot cancel an acquire, and it still hands the next free connection
     * to a caller that walked away, and still counts that caller as a borrower.
     *
     * This destroys a connection whose command it abandoned rather than returns it, because the
     * reply is still in flight and would read as the answer to whichever command borrows it next.
     */
    private async withClient(run: (client: CrawlHistoryRedis) => Promise<void>): Promise<void> {
        const client = await this.pool.acquire()
        let timer: NodeJS.Timeout | undefined
        try {
            await Promise.race([
                run(client),
                new Promise<never>((_resolve, reject) => {
                    timer = setTimeout(
                        () => reject(new Error('crawl history command timed out')),
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
