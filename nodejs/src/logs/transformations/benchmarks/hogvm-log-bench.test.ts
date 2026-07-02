import { compileHog } from '~/cdp/templates/compiler'

import { BENCH_LOG_RECORDS, BENCH_PROGRAMS, buildBenchGlobals } from './fixtures'
import { execBenchProgram } from './hogvm-exec'

jest.setTimeout(30_000)

describe('hogvm log transformation benchmark programs', () => {
    // Ceiling is ~40x the expected mean (~25µs/record): generous enough to never flake on a
    // loaded CI worker, tight enough to catch an order-of-magnitude VM regression.
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

    it('body-regex-scrub redacts emails and secret keys', async () => {
        const program = BENCH_PROGRAMS.find((p) => p.id === 'body-regex-scrub')!
        const bytecode = await compileHog(program.hog)
        const record = BENCH_LOG_RECORDS.find((r) => r.id === 'plain-body')!.record

        const { execResult } = execBenchProgram(bytecode, buildBenchGlobals(record, program.inputs), TIMEOUT_MS)

        const body = (execResult!.result as { body: string }).body
        expect(body).not.toContain('jane.doe@example.com')
        expect(body).not.toContain('ops@example.com')
        expect(body).not.toContain('sk_fake_')
        expect(body).toContain('[REDACTED]')
    })

    it('redact-attributes hashes only the configured keys', async () => {
        const program = BENCH_PROGRAMS.find((p) => p.id === 'redact-attributes')!
        const bytecode = await compileHog(program.hog)
        const record = BENCH_LOG_RECORDS.find((r) => r.id === 'plain-body')!.record

        const { execResult } = execBenchProgram(bytecode, buildBenchGlobals(record, program.inputs), TIMEOUT_MS)

        const attributes = (execResult!.result as { attributes: Record<string, string> }).attributes
        expect(attributes['user.email']).toMatch(/^[a-f0-9]{64}$/)
        expect(attributes['distinct_id']).toMatch(/^[a-f0-9]{64}$/)
        expect(attributes['http.method']).toBe('POST')
    })

    it('conditional-drop returns null for matching records and passes others', async () => {
        const program = BENCH_PROGRAMS.find((p) => p.id === 'conditional-drop')!
        const bytecode = await compileHog(program.hog)

        const noisy = BENCH_LOG_RECORDS.find((r) => r.id === 'fat-attributes')!.record
        const dropped = execBenchProgram(bytecode, buildBenchGlobals(noisy, program.inputs), TIMEOUT_MS)
        expect(dropped.execResult?.result).toBeNull()

        const kept = BENCH_LOG_RECORDS.find((r) => r.id === 'plain-body')!.record
        const keptResult = execBenchProgram(bytecode, buildBenchGlobals(kept, program.inputs), TIMEOUT_MS)
        expect(keptResult.execResult?.result).not.toBeNull()
    })
})
