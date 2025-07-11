import { DEFAULT_TIMEOUT_MS, exec, ExecOptions, ExecResult } from '@posthog/hogvm'
import crypto from 'crypto'
import { Counter } from 'prom-client'
import RE2 from 're2'

import { Semaphore } from './sempahore'

export const MAX_THREAD_WAIT_TIME_MS = 200

const hogExecThreadReliefCounter = new Counter({
    name: 'cdp_hog_function_execution_thread_relief',
    help: 'Whether the hog function execution was blocked by the thread relief',
    // We have a timeout so we don't need to worry about much more than that
    labelNames: ['waited'],
})

const semaphore = new Semaphore(1)

let threadRelief: {
    startedAt: number
    promise: Promise<void>
} | null = null

const waitForThreadRelief = async (timeout: number = DEFAULT_TIMEOUT_MS): Promise<boolean> => {
    if (!threadRelief) {
        threadRelief = {
            startedAt: performance.now(),
            promise: new Promise((resolve) => {
                setTimeout(() => {
                    threadRelief = null
                    resolve()
                }, 0)
            }),
        }
    }

    if (performance.now() - threadRelief.startedAt < timeout) {
        return false
    }

    await threadRelief.promise

    return true
}

// NOTE: Hog execution can be expensive and in really bad cases can block the event loop for a long time.
// To work around this we have a check when we run it to make sure that
export async function execHog(
    bytecode: any,
    options?: ExecOptions
): Promise<{
    execResult?: ExecResult
    error?: any
    durationMs: number
    waitedForThreadRelief: boolean
}> {
    return await semaphore.run(async () => {
        const waitedForInitialRelief = await waitForThreadRelief(options?.timeout)
        const result = execHogImmediate(bytecode, options)
        const waitedForFinalRelief = await waitForThreadRelief(options?.timeout)

        const waitedForThreadRelief = waitedForInitialRelief || waitedForFinalRelief
        hogExecThreadReliefCounter.inc({ waited: waitedForThreadRelief ? 'true' : 'false' })

        return {
            ...result,
            waitedForThreadRelief,
        }
    })
}

function execHogImmediate(
    bytecode: any,
    options?: ExecOptions
): {
    execResult?: ExecResult
    error?: any
    durationMs: number
} {
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
}
