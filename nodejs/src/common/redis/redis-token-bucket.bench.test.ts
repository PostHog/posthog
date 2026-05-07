/**
 * Benchmark — V2 pipelined vs V3 multi-key + coalescing for the CDP rate limiter.
 *
 * Runs against the local docker-compose Redis (or wherever `createHub`'s
 * Redis points). Skipped by default — set `RUN_BENCHMARKS=1` to opt in.
 *
 *   RUN_BENCHMARKS=1 hogli test nodejs/src/common/redis/redis-token-bucket.bench.test.ts --forceExit
 *
 * Knobs via env vars:
 *   BENCH_BATCHES          default 100   batch invocations per run
 *   BENCH_EVENTS_PER_BATCH default 200   events per batch (rateLimitMany call)
 *   BENCH_UNIQUE_FUNCTIONS default 50    unique function ids in the batch
 *
 * What it measures:
 *   - Wall-clock time + ops/sec for each path.
 *   - Redis-side `INFO commandstats` delta per command (calls, total μs, μs/call).
 *   - Reduction percentages in the summary.
 *
 * What it asserts (light — perf varies by host):
 *   - V3 fires strictly fewer Redis commands than V2 for the same workload.
 *   - V3 spends strictly fewer total Redis-side μs than V2.
 */
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'

import { deleteKeysWithPrefix } from '../../cdp/_tests/redis'
import { BASE_REDIS_KEY, HogRateLimiterService } from '../../cdp/services/monitoring/hog-rate-limiter.service'
import { RedisV2, createRedisV2PoolFromConfig } from './redis-v2'

const BATCHES = Number(process.env.BENCH_BATCHES ?? 100)
const EVENTS_PER_BATCH = Number(process.env.BENCH_EVENTS_PER_BATCH ?? 200)
const UNIQUE_FUNCTIONS = Number(process.env.BENCH_UNIQUE_FUNCTIONS ?? 50)
const TRACKED = ['evalsha', 'hget', 'hmget', 'hset', 'expire', 'pexpire', 'pttl', 'ttl']

type CommandStats = Map<string, { calls: number; usec: number; rejected: number }>

const benchDescribe = process.env.RUN_BENCHMARKS ? describe : describe.skip

benchDescribe('benchmark: token bucket V2 vs V3 multi-key', () => {
    let hub: Hub
    let redis: RedisV2
    let rateLimiter: HogRateLimiterService

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
        rateLimiter = new HogRateLimiterService({ bucketSize: 10000, refillRate: 10, ttl: 60 * 60 * 24 }, redis)
    })

    afterAll(async () => {
        await deleteKeysWithPrefix(redis, BASE_REDIS_KEY)
        await closeHub(hub)
    })

    const buildWorkload = (): [string, number][][] => {
        const ids = Array.from({ length: UNIQUE_FUNCTIONS }, (_, i) => `bench-fn-${i.toString().padStart(4, '0')}`)
        return Array.from({ length: BATCHES }, () =>
            Array.from(
                { length: EVENTS_PER_BATCH },
                () => [ids[Math.floor(Math.random() * ids.length)], 1] as [string, number]
            )
        )
    }

    const readCommandStats = async (): Promise<CommandStats> => {
        const stats: CommandStats = new Map()
        const raw = await redis.useClient({ name: 'info' }, async (client) => client.info('commandstats'))
        if (!raw) {
            return stats
        }
        for (const line of raw.split('\n')) {
            // cmdstat_evalsha:calls=12,usec=4567,usec_per_call=380.58,rejected_calls=0,failed_calls=0
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

    const coalesce = (idCosts: [string, number][]): [string, number][] => {
        const m = new Map<string, number>()
        for (const [id, cost] of idCosts) {
            m.set(id, (m.get(id) ?? 0) + cost)
        }
        return [...m.entries()]
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
        method: 'rateLimitMany' | 'rateLimitManyMulti',
        workload: [string, number][][]
    ): Promise<{ wallMs: number; stats: CommandStats }> => {
        // Warm-up: load the script + connection establish, not part of the measurement.
        await rateLimiter[method]([['warmup', 1]])
        await redis.useClient({ name: 'reset' }, async (client) => client.config('RESETSTAT'))

        const before = await readCommandStats()
        const start = process.hrtime.bigint()
        for (const batch of workload) {
            const input = method === 'rateLimitManyMulti' ? coalesce(batch) : batch
            await rateLimiter[method](input)
        }
        const end = process.hrtime.bigint()
        const after = await readCommandStats()

        const wallMs = Number(end - start) / 1e6
        const stats = diffStats(before, after)
        printRun(label, wallMs, stats)
        return { wallMs, stats }
    }

    it('V3 multi-key + coalescing reduces Redis commands and CPU vs V2 pipelined', async () => {
        console.log(`Workload: ${BATCHES} batches × ${EVENTS_PER_BATCH} events × ${UNIQUE_FUNCTIONS} unique fns`)

        // Pre-clean so neither run pays a first-call cost the other doesn't.
        await deleteKeysWithPrefix(redis, BASE_REDIS_KEY)
        const workload = buildWorkload()

        const v2 = await runOne('rateLimitMany (V2 pipelined)', 'rateLimitMany', workload)
        await deleteKeysWithPrefix(redis, BASE_REDIS_KEY)
        const v3 = await runOne('rateLimitManyMulti (V3 multi-key + coalesced)', 'rateLimitManyMulti', workload)

        const totalV2Calls = TRACKED.reduce((s, c) => s + (v2.stats.get(c)?.calls ?? 0), 0)
        const totalV3Calls = TRACKED.reduce((s, c) => s + (v3.stats.get(c)?.calls ?? 0), 0)
        const totalV2Usec = TRACKED.reduce((s, c) => s + (v2.stats.get(c)?.usec ?? 0), 0)
        const totalV3Usec = TRACKED.reduce((s, c) => s + (v3.stats.get(c)?.usec ?? 0), 0)

        console.log(`\n=== Summary ===`)
        console.log(
            `Wall time:      V2 ${v2.wallMs.toFixed(1)} ms → V3 ${v3.wallMs.toFixed(1)} ms  (${(
                v2.wallMs / v3.wallMs
            ).toFixed(2)}× faster)`
        )
        console.log(
            `Redis cmds:     V2 ${totalV2Calls.toLocaleString()} → V3 ${totalV3Calls.toLocaleString()}  (${(
                (1 - totalV3Calls / totalV2Calls) *
                100
            ).toFixed(1)}% reduction)`
        )
        console.log(
            `Redis CPU (μs): V2 ${totalV2Usec.toLocaleString()} → V3 ${totalV3Usec.toLocaleString()}  (${(
                (1 - totalV3Usec / totalV2Usec) *
                100
            ).toFixed(1)}% reduction)`
        )

        // Light regression guards: V3 must always do less Redis work for this workload shape.
        // (Wall time is host-dependent and not asserted.)
        expect(totalV3Calls).toBeLessThan(totalV2Calls)
        expect(totalV3Usec).toBeLessThan(totalV2Usec)
    }, 120_000)
})
