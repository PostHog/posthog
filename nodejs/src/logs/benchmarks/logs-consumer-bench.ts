/**
 * Throughput benchmark for the logs consumer: the original consumer (before the framework rewrite),
 * the framework consumer, and the Rust port all replay the same workload files and print the same
 * result JSON. `run-logs-bench.sh` drives the three; this file is the Node side.
 *
 *   tsx logs-consumer-bench.ts generate <dir>
 *   tsx logs-consumer-bench.ts run <framework|before> <workload.json> <result.json> [measuredPasses] [warmupPasses]
 *   tsx logs-consumer-bench.ts compare <result.json>...
 */
import { mkdirSync, readFileSync, writeFileSync } from 'fs'
import Redis from 'ioredis'
import { join, resolve } from 'path'
import { register } from 'prom-client'

import { parseJSON } from '~/common/utils/json-parse'

import {
    FRAMEWORK_CLASSES,
    type ParityConsumerClasses,
    buildParityConsumer,
    toKafkaMessage,
} from '../parity/parity-harness'
import type { ParityScenario } from '../parity/parity-types'
import { DEFAULT_BENCH_OPTIONS, buildBenchWorkloads } from './bench-workloads'

/** The schema every implementation prints, so `compare` reads Node and Rust results alike. */
export type BenchResult = {
    implementation: string
    workload: string
    passes: number
    batches: number
    messages: number
    records: number
    input_bytes: number
    produced: number
    wall_ms: number
    cpu_ms: number
    peak_rss_mb: number
    messages_per_s: number
    records_per_s: number
    input_mb_per_s: number
    batch_ms: { mean: number; p50: number; p95: number; p99: number; max: number }
}

function percentile(sorted: number[], p: number): number {
    return sorted[Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length))]
}

type BaselineModule = {
    LogsIngestionConsumer: ParityConsumerClasses['logs']
    TracesIngestionConsumer: ParityConsumerClasses['traces']
}

/** Rate-limiter and sampling buckets the consumers write, so a run never clears other data in Redis. */
const BENCH_REDIS_KEY_PATTERNS = [
    '@posthog*/logs-rate-limiter/*',
    '@posthog*/traces-rate-limiter/*',
    '@posthog*/logs-sampling-rate/*',
]

async function clearBenchRedisKeys(): Promise<void> {
    // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
    const redis = new Redis('redis://127.0.0.1:6379')
    try {
        for (const pattern of BENCH_REDIS_KEY_PATTERNS) {
            let cursor = '0'
            do {
                const [next, keys] = await redis.scan(cursor, 'MATCH', pattern, 'COUNT', 1000)
                if (keys.length > 0) {
                    await redis.del(...keys)
                }
                cursor = next
            } while (cursor !== '0')
        }
    } finally {
        await redis.quit()
    }
}

async function loadClasses(implementation: string): Promise<ParityConsumerClasses> {
    if (implementation === 'framework') {
        return FRAMEWORK_CLASSES
    }
    if (implementation === 'before') {
        // Written by run-logs-bench.sh from git; never committed. The harness has already loaded the
        // current consumer, which registered the same metric names, and nothing here reads them.
        // The specifier is built at run time so the build never resolves the uncommitted directory.
        register.clear()
        const baseline = join(__dirname, '.baseline')
        const logs = (await import(join(baseline, 'logs-ingestion-consumer.ts'))) as BaselineModule
        const traces = (await import(join(baseline, 'traces-ingestion-consumer.ts'))) as BaselineModule
        return { logs: logs.LogsIngestionConsumer, traces: traces.TracesIngestionConsumer }
    }
    throw new Error(`unknown implementation ${implementation}`)
}

async function run(implementation: string, workloadPath: string, passes: number, warmup: number): Promise<BenchResult> {
    const scenario = parseJSON(readFileSync(workloadPath, 'utf8')) as ParityScenario
    await clearBenchRedisKeys()

    const { consumer, outputs } = buildParityConsumer(scenario, {
        classes: await loadClasses(implementation),
        discard: true,
    })
    const batches = scenario.batches.map((batch) => batch.map(toKafkaMessage))
    const runBatch = async (index: number): Promise<void> => {
        const { backgroundTask } = await consumer.processKafkaBatch(batches[index])
        await backgroundTask
    }

    for (let pass = 0; pass < warmup; pass++) {
        for (let i = 0; i < batches.length; i++) {
            await runBatch(i)
        }
    }
    outputs.producedCount = 0

    const batchMs: number[] = []
    let peakRss = process.memoryUsage().rss
    const cpuStart = process.cpuUsage()
    const wallStart = performance.now()
    for (let pass = 0; pass < passes; pass++) {
        for (let i = 0; i < batches.length; i++) {
            const start = performance.now()
            await runBatch(i)
            batchMs.push(performance.now() - start)
            peakRss = Math.max(peakRss, process.memoryUsage().rss)
        }
    }
    const wallMs = performance.now() - wallStart
    const cpu = process.cpuUsage(cpuStart)

    const messagesPerPass = scenario.batches.reduce((n, batch) => n + batch.length, 0)
    const recordsPerPass = scenario.batches.reduce(
        (n, batch) =>
            n + batch.reduce((m, msg) => m + Number(msg.headers.find(([k]) => k === 'record_count')?.[1] ?? 0), 0),
        0
    )
    const bytesPerPass = batches.reduce((n, batch) => n + batch.reduce((m, msg) => m + (msg.value?.length ?? 0), 0), 0)
    const sorted = [...batchMs].sort((a, b) => a - b)
    const seconds = wallMs / 1000
    return {
        implementation: `node-${implementation}`,
        workload: scenario.name,
        passes,
        batches: batchMs.length,
        messages: messagesPerPass * passes,
        records: recordsPerPass * passes,
        input_bytes: bytesPerPass * passes,
        produced: outputs.producedCount,
        wall_ms: wallMs,
        cpu_ms: (cpu.user + cpu.system) / 1000,
        peak_rss_mb: peakRss / 1024 / 1024,
        messages_per_s: (messagesPerPass * passes) / seconds,
        records_per_s: (recordsPerPass * passes) / seconds,
        input_mb_per_s: (bytesPerPass * passes) / 1024 / 1024 / seconds,
        batch_ms: {
            mean: batchMs.reduce((a, b) => a + b, 0) / batchMs.length,
            p50: percentile(sorted, 50),
            p95: percentile(sorted, 95),
            p99: percentile(sorted, 99),
            max: sorted[sorted.length - 1],
        },
    }
}

/** Each implementation's median round by records/s, so one noisy round does not decide a row. */
function medianRounds(results: BenchResult[]): BenchResult[] {
    const groups = new Map<string, BenchResult[]>()
    for (const r of results) {
        const key = `${r.workload}\u0000${r.implementation}`
        groups.set(key, [...(groups.get(key) ?? []), r])
    }
    return [...groups.values()].map((rounds) => {
        const sorted = [...rounds].sort((a, b) => a.records_per_s - b.records_per_s)
        return sorted[Math.floor(sorted.length / 2)]
    })
}

function compare(paths: string[]): string {
    const results = medianRounds(paths.map((path) => parseJSON(readFileSync(path, 'utf8')) as BenchResult))
    const rounds = paths.length / Math.max(1, results.length)
    const order = ['node-before', 'node-framework', 'rust']
    const workloads = [...new Set(results.map((r) => r.workload))].sort()
    const lines = [
        `Median of ${rounds} rounds per implementation.`,
        '',
        '| workload | implementation | records/s | MB/s in | batch p50 ms | batch p99 ms | CPU ms / 1k records | peak RSS MB | vs before |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|',
    ]
    for (const workload of workloads) {
        const rows = results
            .filter((r) => r.workload === workload)
            .sort((a, b) => order.indexOf(a.implementation) - order.indexOf(b.implementation))
        const before = rows.find((r) => r.implementation === 'node-before')
        for (const r of rows) {
            const speedup = before ? `${(r.records_per_s / before.records_per_s).toFixed(2)}x` : ''
            lines.push(
                `| ${workload} | ${r.implementation} | ${Math.round(r.records_per_s).toLocaleString('en-US')} | ${r.input_mb_per_s.toFixed(1)} | ${r.batch_ms.p50.toFixed(1)} | ${r.batch_ms.p99.toFixed(1)} | ${((r.cpu_ms / r.records) * 1000).toFixed(1)} | ${r.peak_rss_mb.toFixed(0)} | ${speedup} |`
            )
        }
    }
    return lines.join('\n')
}

async function main(): Promise<void> {
    const [command, ...args] = process.argv.slice(2)
    if (command === 'generate') {
        const dir = resolve(args[0])
        mkdirSync(dir, { recursive: true })
        // Metric rules skip records older than 20 minutes, and a full run takes longer than that.
        // Records stamped ahead of the clock pass the age gate in every round of every implementation.
        const nowMs = Date.now() + 12 * 3600 * 1000
        for (const workload of await buildBenchWorkloads({ ...DEFAULT_BENCH_OPTIONS, nowMs })) {
            writeFileSync(join(dir, `${workload.name}.json`), JSON.stringify(workload))
        }
    } else if (command === 'run') {
        // A file, not stdout: the consumer logs to stdout.
        const [implementation, workload, out, passes = '10', warmup = '2'] = args
        writeFileSync(out, JSON.stringify(await run(implementation, workload, Number(passes), Number(warmup))) + '\n')
    } else if (command === 'compare') {
        process.stdout.write(compare(args) + '\n')
    } else {
        throw new Error(`unknown command ${command}`)
    }
}

void main().then(
    () => process.exit(0),
    (error) => {
        console.error(error)
        process.exit(1)
    }
)
