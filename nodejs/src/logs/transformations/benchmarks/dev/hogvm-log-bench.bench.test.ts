import { compileHog } from '~/cdp/templates/compiler'

import { BENCH_LOG_RECORDS, BENCH_PROGRAMS, buildBenchGlobals } from '../fixtures'
import { execBenchProgram } from '../hogvm-exec'

// Wall-clock benchmark for the log transformation programs. It lives under dev/ so
// `testPathIgnorePatterns` keeps it out of CI: the mean-per-record ceiling and the
// per-execution timeout both measure elapsed time, which a scheduling stall on a
// shared runner is enough to trip. Run it on demand:
//   cd nodejs && pnpm exec jest --testPathIgnorePatterns '/node_modules/' \
//     src/logs/transformations/benchmarks/dev/hogvm-log-bench.bench.test.ts
// The standalone harness in ../hogvm-log-bench.ts reports the full percentile table.

jest.setTimeout(30_000)

describe('hogvm log transformation benchmark programs', () => {
    // Ceiling is ~40x the expected mean (~25µs/record): generous enough to never flake on a
    // loaded worker, tight enough to catch an order-of-magnitude VM regression.
    const CEILING_US_PER_RECORD = 1000
    const ITERATIONS = 200
    const TIMEOUT_MS = 10

    it.each(BENCH_PROGRAMS.map((p) => [p.id, p] as const))(
        'program %s executes correctly and under the per-record ceiling',
        async (_id, program) => {
            expect.hasAssertions()
            const bytecode = await compileHog(program.hog)

            for (const { id: recordId, record } of BENCH_LOG_RECORDS) {
                // Warmup (JIT, RE2 compile)
                for (let i = 0; i < 50; i++) {
                    execBenchProgram(bytecode, buildBenchGlobals(record, program.inputs), TIMEOUT_MS)
                }

                let totalMs = 0
                for (let i = 0; i < ITERATIONS; i++) {
                    const globals = buildBenchGlobals(record, program.inputs)
                    const { error, execResult, durationMs } = execBenchProgram(bytecode, globals, TIMEOUT_MS)
                    expect(error).toBeUndefined()
                    expect(execResult?.error).toBeUndefined()
                    expect(execResult?.finished).toBe(true)
                    totalMs += durationMs
                }

                const meanUs = (totalMs / ITERATIONS) * 1000
                expect(meanUs).toBeLessThan(CEILING_US_PER_RECORD)

                if (process.env.BENCH_DEBUG) {
                    console.info(`${program.id} × ${recordId}: ${meanUs.toFixed(1)}µs/record`)
                }
            }
        }
    )
})
