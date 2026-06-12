import crypto from 'crypto'

import { ExecResult, convertHogToJS, exec } from '@posthog/hogvm'

import { createTrackedRE2 } from '../../../utils/tracked-re2'
import type { BenchGlobals } from './fixtures'

// Mirrors the external bindings of cdp/utils/hog-exec.ts `execHogImmediate` so the benchmark
// measures the same VM + RE2 + crypto stack the production primitive will use, without
// importing CDP service code into a dev-only harness.
export function execBenchProgram(
    bytecode: unknown,
    globals: BenchGlobals,
    timeoutMs: number
): { execResult?: ExecResult; error?: unknown; durationMs: number } {
    const start = performance.now()
    let execResult: ExecResult | undefined
    let error: unknown

    try {
        execResult = exec(bytecode as any, {
            globals,
            timeout: timeoutMs,
            maxAsyncSteps: 0,
            functions: {
                print: () => {},
            },
            external: {
                regex: {
                    match: (regex, str) => createTrackedRE2(regex, undefined, 'logs-bench:regex.match').test(str),
                    extract: (regex, str) => {
                        const match = createTrackedRE2(regex, undefined, 'logs-bench:regex.extract').exec(str)
                        if (!match) {
                            return ''
                        }
                        return match.length > 1 ? (match[1] ?? '') : (match[0] ?? '')
                    },
                },
                crypto,
            },
        })
        if (execResult?.finished) {
            // The production primitive converts Hog values (Maps) back to plain JS before
            // merging into the record, so the measured cost includes that conversion.
            execResult.result = convertHogToJS(execResult.result)
        }
    } catch (e) {
        error = e
    }

    return { execResult, error, durationMs: performance.now() - start }
}
