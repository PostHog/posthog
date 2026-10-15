import { compileHog } from '~/cdp/templates/compiler'

import { computeBenchStats, printBenchStatsTable } from './bench-stats'
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

async function main(): Promise<void> {
    console.info(`Compiling ${BENCH_PROGRAMS.length} Hog programs via bin/hog...`)
    const compiled = await Promise.all(
        BENCH_PROGRAMS.map(async (program) => ({ program, bytecode: await compileHog(program.hog) }))
    )

    const allStats = []

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

            allStats.push(computeBenchStats(program.id, recordId, durationsUs))
        }
    }

    printBenchStatsTable('HogVM per-record execution cost', ITERATIONS, allStats)

    const overallMean = allStats.reduce((a, s) => a + s.meanUs, 0) / allStats.length
    console.info(`\nOverall mean across programs/records: ${overallMean.toFixed(1)}µs/record`)
    console.info('Capacity reference: top org sustains ~250k records/s; 25µs/record ≈ 6 dedicated cores/function.')
}

main().catch((error) => {
    console.error(error)
    process.exit(1)
})
