import { performance } from 'perf_hooks'

import { compileHog } from '~/cdp/templates/compiler'

import { encodeLogAttributeValue } from '../../attribute-value'
import type { LogRecord } from '../../log-record-avro'
import { buildLogRecordGlobals, executeLogTransformation } from '../hog-log-exec'
import { computeBenchStats, printBenchStatsTable } from './bench-stats'
import { BENCH_LOG_RECORDS, BENCH_PROGRAMS } from './fixtures'

// Micro-benchmark of the PRODUCTION per-record transformation path, unlike
// hogvm-log-bench.ts which times raw HogVM execution only. The measured interval
// covers everything transformSingleRecord does per record per function:
// buildLogRecordGlobals (decode attribute maps, hex-encode ids) +
// executeLogTransformation (VM run + convertHogToJS + applyTransformResult re-encode).
// The gap between this number and hogvm-log-bench's is TS-side per-record overhead.
//
// Run with:
//   cd nodejs && pnpm exec tsx src/logs/transformations/benchmarks/transformer-log-bench.ts
//
// Pass/fail gate: exits 1 when the overall mean exceeds
// REGRESSION_CEILING_US_PER_RECORD — ~10x the expected mean, generous enough to
// never flake on a loaded machine, tight enough to catch an order-of-magnitude
// regression in the per-record path.

const WARMUP_ITERATIONS = 500
const ITERATIONS = 5_000
const TIMEOUT_MS = 10
const REGRESSION_CEILING_US_PER_RECORD = 500

// Wire-form encoding like the consumer's Avro decode produces: attribute values are
// JSON-encoded strings.
function toWireRecord(record: LogRecord): LogRecord {
    return {
        ...record,
        attributes: record.attributes
            ? Object.fromEntries(Object.entries(record.attributes).map(([k, v]) => [k, encodeLogAttributeValue(v)]))
            : record.attributes,
        resource_attributes: record.resource_attributes
            ? Object.fromEntries(
                  Object.entries(record.resource_attributes).map(([k, v]) => [k, encodeLogAttributeValue(v)])
              )
            : record.resource_attributes,
    }
}

async function main(): Promise<void> {
    console.info(`Compiling ${BENCH_PROGRAMS.length} Hog programs via bin/hog...`)
    const compiled = await Promise.all(
        BENCH_PROGRAMS.map(async (program) => ({ program, bytecode: await compileHog(program.hog) }))
    )

    const project = { id: 1, name: 'bench', url: 'http://localhost:8010/project/1' }
    const allStats = []

    for (const { program, bytecode } of compiled) {
        for (const { id: recordId, record } of BENCH_LOG_RECORDS) {
            const wireRecord = toWireRecord(record)

            // Fresh wire-record clone per iteration, kept outside the timer: execution
            // mutates the record in place, and reusing a scrubbed record would let later
            // iterations skip the regex-replace work.
            const runOnce = (): { durationUs: number; status: string } => {
                // oxlint-disable-next-line eslint-js/no-restricted-syntax
                const rec: LogRecord = JSON.parse(JSON.stringify(wireRecord))
                const start = performance.now()
                const globals = buildLogRecordGlobals(rec, project, { ...program.inputs })
                const outcome = executeLogTransformation(bytecode, rec, globals, { timeoutMs: TIMEOUT_MS })
                const durationUs = (performance.now() - start) * 1000
                return { durationUs, status: outcome.status }
            }

            for (let i = 0; i < WARMUP_ITERATIONS; i++) {
                const { status } = runOnce()
                if (status === 'failed') {
                    throw new Error(`Program ${program.id} failed on record ${recordId} during warmup`)
                }
            }

            const durationsUs: number[] = []
            for (let i = 0; i < ITERATIONS; i++) {
                const { durationUs, status } = runOnce()
                if (status === 'failed') {
                    throw new Error(`Program ${program.id} failed on record ${recordId}`)
                }
                durationsUs.push(durationUs)
            }

            allStats.push(computeBenchStats(program.id, recordId, durationsUs))
        }
    }

    printBenchStatsTable('Production-path per-record cost', ITERATIONS, allStats)

    const overallMeanUs = allStats.reduce((a, s) => a + s.meanUs, 0) / allStats.length
    console.info(`\nMETRIC overall_mean_us_per_record: ${overallMeanUs.toFixed(1)}`)
    if (overallMeanUs > REGRESSION_CEILING_US_PER_RECORD) {
        console.error(
            `FAIL: overall mean ${overallMeanUs.toFixed(1)}µs/record exceeds regression ceiling of ${REGRESSION_CEILING_US_PER_RECORD}µs/record`
        )
        process.exit(1)
    }
}

main().catch((error) => {
    console.error(error)
    process.exit(1)
})
