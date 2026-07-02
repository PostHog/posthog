import { compileHog } from '~/cdp/templates/compiler'

import { BENCH_LOG_RECORDS, BENCH_PROGRAMS, buildBenchGlobals } from './fixtures'
import { execBenchProgram } from './hogvm-exec'

// Micro-benchmark: TS HogVM cost per log record per transformation program.
//
// Run with:
//   cd nodejs && pnpm exec tsx src/logs/transformations/benchmarks/hogvm-log-bench.ts
//
// The numbers from this harness parameterize the log transformation budgets
// (per-record timeout, per-message budget, watcher cost curve). Re-run after
// hogvm upgrades or when changing the globals shape.

const WARMUP_ITERATIONS = 500
const ITERATIONS = 5_000
const TIMEOUT_MS = 10

interface BenchStats {
    programId: string
    recordId: string
    meanUs: number
    p50Us: number
    p95Us: number
    p99Us: number
    maxUs: number
}

function percentile(sorted: number[], p: number): number {
    const idx = Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length))
    return sorted[idx]
}

async function main(): Promise<void> {
    console.info(`Compiling ${BENCH_PROGRAMS.length} Hog programs via bin/hog...`)
    const compiled = await Promise.all(
        BENCH_PROGRAMS.map(async (program) => ({ program, bytecode: await compileHog(program.hog) }))
    )

    const allStats: BenchStats[] = []

    for (const { program, bytecode } of compiled) {
        for (const { id: recordId, record } of BENCH_LOG_RECORDS) {
            // Fresh globals each iteration: transformations mutate the record, and reusing
            // a scrubbed record would let later iterations skip the regex-replace work.
            for (let i = 0; i < WARMUP_ITERATIONS; i++) {
                const result = execBenchProgram(bytecode, buildBenchGlobals(record, program.inputs), TIMEOUT_MS)
                if (result.error || result.execResult?.error) {
                    throw new Error(
                        `Program ${program.id} failed on record ${recordId}: ${result.error ?? result.execResult?.error}`
                    )
                }
            }

            const durationsUs: number[] = []
            for (let i = 0; i < ITERATIONS; i++) {
                const globals = buildBenchGlobals(record, program.inputs)
                const { durationMs } = execBenchProgram(bytecode, globals, TIMEOUT_MS)
                durationsUs.push(durationMs * 1000)
            }

            durationsUs.sort((a, b) => a - b)
            allStats.push({
                programId: program.id,
                recordId,
                meanUs: durationsUs.reduce((a, b) => a + b, 0) / durationsUs.length,
                p50Us: percentile(durationsUs, 50),
                p95Us: percentile(durationsUs, 95),
                p99Us: percentile(durationsUs, 99),
                maxUs: durationsUs[durationsUs.length - 1],
            })
        }
    }

    console.info(`\nHogVM per-record execution cost (${ITERATIONS} iterations each, µs):\n`)
    const header = ['program', 'record', 'mean', 'p50', 'p95', 'p99', 'max']
    const rows = allStats.map((s) => [
        s.programId,
        s.recordId,
        s.meanUs.toFixed(1),
        s.p50Us.toFixed(1),
        s.p95Us.toFixed(1),
        s.p99Us.toFixed(1),
        s.maxUs.toFixed(1),
    ])
    const widths = header.map((h, i) => Math.max(h.length, ...rows.map((r) => r[i].length)))
    console.info(header.map((h, i) => h.padEnd(widths[i])).join('  '))
    for (const row of rows) {
        console.info(row.map((c, i) => c.padEnd(widths[i])).join('  '))
    }

    const overallMean = allStats.reduce((a, s) => a + s.meanUs, 0) / allStats.length
    console.info(`\nOverall mean across programs/records: ${overallMean.toFixed(1)}µs/record`)
    console.info('Capacity reference: top org sustains ~250k records/s; 25µs/record ≈ 6 dedicated cores/function.')
}

main().catch((error) => {
    console.error(error)
    process.exit(1)
})
