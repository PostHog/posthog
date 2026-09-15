import { performance } from 'perf_hooks'

import { compileHog } from '~/cdp/templates/compiler'

import { encodeLogAttributeValue } from '../../attribute-value'
import type { LogRecord } from '../../log-record-avro'
import { buildLogRecordGlobals, executeLogTransformation } from '../hog-log-exec'
import { BENCH_LOG_RECORDS, BENCH_PROGRAMS } from './fixtures'

// Micro-benchmark of the PRODUCTION per-record transformation path, unlike
// hogvm-log-bench.ts which times raw HogVM execution only. For each record this
// times what LogsTransformerService.transformSingleRecord does per function:
//   buildLogRecordGlobals (decode attribute maps, hex-encode ids) + executeLogTransformation
//   (VM run + convertHogToJS + applyTransformResult re-encode).
// The gap between this number and hogvm-log-bench's is TS-side per-record overhead.
//
// Run with:
//   cd nodejs && pnpm exec tsx src/logs/transformations/benchmarks/transformer-log-bench.ts

const WARMUP_ITERATIONS = 500
const ITERATIONS = 5_000
const TIMEOUT_MS = 10

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

    const project = { id: 1, name: 'bench', url: 'http://localhost:8010/project/1' }
    const allStats: BenchStats[] = []
    let overallMeanUs = 0
    let statCount = 0

    for (const { program, bytecode } of compiled) {
        for (const { id: recordId, record } of BENCH_LOG_RECORDS) {
            const wireRecord = toWireRecord(record)

            // One full production-path run per iteration: fresh wire record each time
            // because execution mutates it in place (scrubbed bodies would skip regex
            // work on later iterations).
            const runOnce = (): { durationUs: number; status: string } => {
                const rec: LogRecord = JSON.parse(JSON.stringify(wireRecord))
                const globals = buildLogRecordGlobals(rec, project, { ...program.inputs })
                const start = performance.now()
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

            durationsUs.sort((a, b) => a - b)
            const meanUs = durationsUs.reduce((a, b) => a + b, 0) / durationsUs.length
            allStats.push({
                programId: program.id,
                recordId,
                meanUs,
                p50Us: percentile(durationsUs, 50),
                p95Us: percentile(durationsUs, 95),
                p99Us: percentile(durationsUs, 99),
                maxUs: durationsUs[durationsUs.length - 1],
            })
            overallMeanUs += meanUs
            statCount++
        }
    }
    overallMeanUs /= statCount

    console.info(`\nProduction-path per-record cost (${ITERATIONS} iterations each, µs):\n`)
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

    console.info(`\nMETRIC overall_mean_us_per_record: ${overallMeanUs.toFixed(1)}`)
}

main().catch((error) => {
    console.error(error)
    process.exit(1)
})
