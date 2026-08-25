import { compileHog } from '~/cdp/templates/compiler'

import { BENCH_LOG_RECORDS, BENCH_PROGRAMS, buildBenchGlobals } from './fixtures'
import { execBenchProgram } from './hogvm-exec'

// Correctness of the log transformation programs. The wall-clock benchmark lives in
// dev/hogvm-log-bench.bench.test.ts, out of CI. These cases check output only, so the
// per-execution timeout is generous: a scheduling stall must not fail them.
const TIMEOUT_MS = 5_000

describe('hogvm log transformation programs', () => {
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
