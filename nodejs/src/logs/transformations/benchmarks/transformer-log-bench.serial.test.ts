// Serial: concurrent workers invalidate this CPU-performance threshold.
import { compileHog } from '~/cdp/templates/compiler'

import type { LogRecord } from '../../log-record-avro'
import { buildLogRecordGlobals, executeLogTransformation } from '../hog-log-exec'
import { BENCH_LOG_RECORDS, BENCH_PROGRAMS } from './fixtures'

jest.setTimeout(60_000)

describe('logs transformation production-path benchmark', () => {
    // Ceiling is ~14x the expected mean (~35µs/record): generous enough to never flake
    // on a loaded CI worker, tight enough to catch an order-of-magnitude regression in
    // the per-record production path (globals build + VM run + result apply).
    const CEILING_US_PER_RECORD = 500
    const ITERATIONS = 200
    const TIMEOUT_MS = 10

    it.each(BENCH_PROGRAMS.map((p) => [p.id, p] as const))(
        'program %s runs the full per-record path correctly and under the ceiling',
        async (_id, program) => {
            expect.hasAssertions()
            const bytecode = await compileHog(program.hog)
            const project = { id: 1, name: 'bench', url: 'http://localhost:8010/project/1' }

            for (const { id: recordId, record } of BENCH_LOG_RECORDS) {
                // Wire-form clone per iteration: execution mutates the record, and a
                // pre-scrubbed record would let later iterations skip the regex work.
                const runOnce = (): { durationUs: number; status: string } => {
                    // oxlint-disable-next-line eslint-js/no-restricted-syntax
                    const rec: LogRecord = JSON.parse(JSON.stringify(record))
                    const start = performance.now()
                    const globals = buildLogRecordGlobals(rec, project, { ...program.inputs })
                    const outcome = executeLogTransformation(bytecode, rec, globals, { timeoutMs: TIMEOUT_MS })
                    return { durationUs: (performance.now() - start) * 1000, status: outcome.status }
                }

                for (let i = 0; i < 50; i++) {
                    expect(runOnce().status).not.toBe('failed')
                }

                let totalUs = 0
                for (let i = 0; i < ITERATIONS; i++) {
                    const { durationUs, status } = runOnce()
                    expect(status).not.toBe('failed')
                    totalUs += durationUs
                }

                const meanUs = totalUs / ITERATIONS
                expect(meanUs).toBeLessThan(CEILING_US_PER_RECORD)

                if (process.env.BENCH_DEBUG) {
                    console.info(`${program.id} × ${recordId}: ${meanUs.toFixed(1)}µs/record (production path)`)
                }
            }
        }
    )
})
