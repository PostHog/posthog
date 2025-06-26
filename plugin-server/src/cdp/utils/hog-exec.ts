import { exec, ExecOptions, ExecResult } from '@posthog/hogvm'
import crypto from 'crypto'
import RE2 from 're2'

import { Semaphore } from './sempahore'

export const DEFAULT_TIMEOUT_MS = 100

const semaphore = new Semaphore(1)

export async function execHog(
    bytecode: any,
    options?: ExecOptions
): Promise<{
    execResult?: ExecResult
    error?: any
    durationMs: number
}> {
    // Ensure we don't have more than one running in parallel
    return await semaphore.run(async () => {
        // Note - the setTimeout here forces the event loop to run fully before the next call. This is important as we never want hog execution to block the event loop
        await new Promise((r) => setTimeout(r, 0))
        const now = performance.now()
        let execResult: ExecResult | undefined
        let error: any
        try {
            execResult = exec(bytecode, {
                timeout: DEFAULT_TIMEOUT_MS,
                maxAsyncSteps: 0,
                ...options,
                external: {
                    regex: { match: (regex, str) => new RE2(regex).test(str) },
                    crypto,
                    ...options?.external,
                },
            })
        } catch (e) {
            error = e
        }

        return {
            execResult,
            error,
            durationMs: performance.now() - now,
        }
    })
}
