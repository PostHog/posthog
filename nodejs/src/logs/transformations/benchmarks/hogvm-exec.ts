import { ExecResult, convertHogToJS } from '@posthog/hogvm'

import { execHogImmediate } from '~/cdp/utils/hog-exec'

import type { BenchGlobals } from './fixtures'

// Thin wrapper over the production exec primitive so the benchmark measures the same
// VM + RE2 + crypto stack the per-record executor uses, including result conversion.
export function execBenchProgram(
    bytecode: unknown,
    globals: BenchGlobals,
    timeoutMs: number
): { execResult?: ExecResult; error?: unknown; durationMs: number } {
    const { execResult, error, durationMs } = execHogImmediate(bytecode, {
        globals,
        timeout: timeoutMs,
        maxAsyncSteps: 0,
        functions: {
            print: () => {},
        },
    })

    if (execResult?.finished) {
        execResult.result = convertHogToJS(execResult.result)
    }

    return { execResult, error, durationMs }
}
