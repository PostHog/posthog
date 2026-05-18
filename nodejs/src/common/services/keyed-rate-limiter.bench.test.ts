/**
 * Benchmark — `rateLimitMany` (V2 pipelined per-call) vs `rateLimitGrouped`
 * (V3 pipelined + coalesced) on `KeyedRateLimiterService`. Mirrors what the
 * production primary (rateLimitMany) and mirror (rateLimitGrouped) paths
 * actually do.
 *
 * Runs against the local docker-compose Redis (or wherever `createHub`'s
 * Redis points). Skipped by default — set `RUN_BENCHMARKS=1` to opt in.
 *
 *   RUN_BENCHMARKS=1 hogli test nodejs/src/common/services/keyed-rate-limiter.bench.test.ts --forceExit
 *
 * Knobs via env vars:
 *   BENCH_BATCHES          default 100   batch invocations per run
 *   BENCH_EVENTS_PER_BATCH default 200   events per batch (per call)
 *   BENCH_UNIQUE_FUNCTIONS default 50    unique ids in the batch
 *
 * What it measures:
 *   - Wall-clock time + ops/sec for each path.
 *   - Redis-side `INFO commandstats` delta per command (calls, total μs, μs/call).
 *   - Reduction percentages in the summary.
 *
 * What it asserts (light — perf varies by host):
 *   - rateLimitGrouped fires strictly fewer Redis commands than rateLimitMany.
 *   - rateLimitGrouped spends strictly fewer total Redis-side μs.
 */
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { deleteKeysWithPrefix } from '../../cdp/_tests/redis'
import { RedisV2, createRedisV2PoolFromConfig } from '../redis/redis-v2'
import { KeyedRateLimitRequest, KeyedRateLimiterService } from './keyed-rate-limiter.service'

const BATCHES = Number(process.env.BENCH_BATCHES ?? 100)
const EVENTS_PER_BATCH = Number(process.env.BENCH_EVENTS_PER_BATCH ?? 200)
const UNIQUE_FUNCTIONS = Number(process.env.BENCH_UNIQUE_FUNCTIONS ?? 50)
const TRACKED = ['evalsha', 'hget', 'hmget', 'hset', 'expire', 'pexpire', 'pttl', 'ttl']

type CommandStats = Map<string, { calls: number; usec: number; rejected: number }>

const benchDescribe = process.env.RUN_BENCHMARKS ? describe : describe.skip

benchDescribe('benchmark: KeyedRateLimiterService rateLimitMany vs rateLimitGrouped', () => {
    let hub: Hub
    let redis: RedisV2
    let limiter: KeyedRateLimiterService

    beforeAll(async () => {
        hub = await createHub()
        redis = createRedisV2PoolFromConfig({
            connection: hub.CDP_REDIS_HOST
                ? {
                      url: hub.CDP_REDIS_HOST,
                      options: { port: hub.CDP_REDIS_PORT, password: hub.CDP_REDIS_PASSWORD },
                  }
                : { url: hub.REDIS_URL },
            poolMinSize: 1,
            poolMaxSize: 4,
        })
        limiter = new KeyedRateLimiterService(
            { name: 'bench', bucketSize: 10000, refillRate: 10, ttlSeconds: 60 * 60 * 24 },
            redis
        )
    })

    afterAll(async () => {
        await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())
        await closeHub(hub)
    })

    const buildWorkload = (): KeyedRateLimitRequest[][] => {
        const ids = Array.from({ length: UNIQUE_FUNCTIONS }, (_, i) => `bench-${i.toString().padStart(4, '0')}`)
        return Array.from({ length: BATCHES }, () =>
            Array.from({ length: EVENTS_PER_BATCH }, () => ({
                id: ids[Math.floor(Math.random() * ids.length)],
                cost: 1,
            }))
        )
    }

    const readCommandStats = async (): Promise<CommandStats> => {
        const stats: CommandStats = new Map()
        const raw = await redis.useClient({ name: 'info' }, async (client) => client.info('commandstats'))
        if (!raw) {
            return stats
        }
        for (const line of raw.split('\n')) {
            const m = /^cmdstat_([a-z|]+):calls=(\d+),usec=(\d+).*?rejected_calls=(\d+)/.exec(line.trim())
            if (!m) {
                continue
            }
            const [, cmd, calls, usec, rejected] = m
            stats.set(cmd, { calls: Number(calls), usec: Number(usec), rejected: Number(rejected) })
        }
        return stats
    }

    const diffStats = (before: CommandStats, after: CommandStats): CommandStats => {
        const out: CommandStats = new Map()
        for (const cmd of TRACKED) {
            const a = after.get(cmd) ?? { calls: 0, usec: 0, rejected: 0 }
            const b = before.get(cmd) ?? { calls: 0, usec: 0, rejected: 0 }
            out.set(cmd, { calls: a.calls - b.calls, usec: a.usec - b.usec, rejected: a.rejected - b.rejected })
        }
        return out
    }

    const printRun = (label: string, wallMs: number, stats: CommandStats) => {
        const totalCalls = TRACKED.reduce((s, c) => s + (stats.get(c)?.calls ?? 0), 0)
        const totalUsec = TRACKED.reduce((s, c) => s + (stats.get(c)?.usec ?? 0), 0)
        const opsPerSec = ((BATCHES * EVENTS_PER_BATCH) / wallMs) * 1000

        console.log(`\n=== ${label} ===`)
        console.log(`wall:        ${wallMs.toFixed(1)} ms (${opsPerSec.toFixed(0)} events/s)`)
        console.log(`redis-side:  ${totalCalls.toLocaleString()} commands, ${totalUsec.toLocaleString()} μs`)
        console.log(`per-command:`)
        for (const cmd of TRACKED) {
            const s = stats.get(cmd)
            if (!s || s.calls === 0) {
                continue
            }
            const usecPerCall = s.calls > 0 ? (s.usec / s.calls).toFixed(2) : '-'
            console.log(
                `  ${cmd.padEnd(8)} ${s.calls.toLocaleString().padStart(10)} calls, ${s.usec
                    .toLocaleString()
                    .padStart(10)} μs  (${usecPerCall} μs/call)`
            )
        }
    }

    const runOne = async (
        label: string,
        method: 'rateLimitMany' | 'rateLimitGrouped',
        workload: KeyedRateLimitRequest[][]
    ): Promise<{ wallMs: number; stats: CommandStats }> => {
        // Warm-up so script load + connection establish aren't part of the measurement.
        await limiter[method]([{ id: 'warmup', cost: 1 }])
        await redis.useClient({ name: 'reset' }, async (client) => client.config('RESETSTAT'))

        const before = await readCommandStats()
        const start = process.hrtime.bigint()
        for (const batch of workload) {
            await limiter[method](batch)
        }
        const end = process.hrtime.bigint()
        const after = await readCommandStats()

        const wallMs = Number(end - start) / 1e6
        const stats = diffStats(before, after)
        printRun(label, wallMs, stats)
        return { wallMs, stats }
    }

    it('rateLimitGrouped reduces Redis commands and CPU vs rateLimitMany', async () => {
        console.log(`Workload: ${BATCHES} batches × ${EVENTS_PER_BATCH} events × ${UNIQUE_FUNCTIONS} unique fns`)

        await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())
        const workload = buildWorkload()

        const many = await runOne('rateLimitMany (V2 pipelined per-call)', 'rateLimitMany', workload)
        await deleteKeysWithPrefix(redis, limiter.getKeyPrefix())
        const grouped = await runOne('rateLimitGrouped (V3 + coalesced)', 'rateLimitGrouped', workload)

        const totalManyCalls = TRACKED.reduce((s, c) => s + (many.stats.get(c)?.calls ?? 0), 0)
        const totalGroupedCalls = TRACKED.reduce((s, c) => s + (grouped.stats.get(c)?.calls ?? 0), 0)
        const totalManyUsec = TRACKED.reduce((s, c) => s + (many.stats.get(c)?.usec ?? 0), 0)
        const totalGroupedUsec = TRACKED.reduce((s, c) => s + (grouped.stats.get(c)?.usec ?? 0), 0)

        console.log(`\n=== Summary ===`)
        console.log(
            `Wall time:      Many ${many.wallMs.toFixed(1)} ms → Grouped ${grouped.wallMs.toFixed(1)} ms  (${(
                many.wallMs / grouped.wallMs
            ).toFixed(2)}× faster)`
        )
        console.log(
            `Redis cmds:     Many ${totalManyCalls.toLocaleString()} → Grouped ${totalGroupedCalls.toLocaleString()}  (${(
                (1 - totalGroupedCalls / totalManyCalls) *
                100
            ).toFixed(1)}% reduction)`
        )
        console.log(
            `Redis CPU (μs): Many ${totalManyUsec.toLocaleString()} → Grouped ${totalGroupedUsec.toLocaleString()}  (${(
                (1 - totalGroupedUsec / totalManyUsec) *
                100
            ).toFixed(1)}% reduction)`
        )

        expect(totalGroupedCalls).toBeLessThan(totalManyCalls)
        expect(totalGroupedUsec).toBeLessThan(totalManyUsec)
    }, 120_000)
})
