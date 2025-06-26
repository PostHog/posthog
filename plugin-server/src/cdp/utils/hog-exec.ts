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
    result?: ExecResult
    error?: any
    durationMs: number
}> {
    // Ensure we don't have more than one running in parallel
    return await semaphore.withLock(async () => {
        await new Promise((resolve) => process.nextTick(resolve))
        const now = performance.now()
        let result: ExecResult | undefined
        let error: any
        try {
            result = exec(bytecode, {
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
            result,
            error,
            durationMs: performance.now() - now,
        }
    })
}
