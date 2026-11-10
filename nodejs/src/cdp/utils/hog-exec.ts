import crypto from 'crypto'

import { DEFAULT_TIMEOUT_MS, ExecOptions, ExecResult, exec } from '@posthog/hogvm'

import { instrumentFn } from '~/common/tracing/tracing-utils'
import { yieldEventLoopIfNeeded } from '~/common/utils/event-loop-yield'
import { createTrackedRE2 } from '~/common/utils/tracked-re2'

import { deadlineError, deadlineRemainingMs } from './deadline'
import { Semaphore } from './sempahore'

const semaphore = new Semaphore(1)

export async function execHog(
    bytecode: any,
    options?: ExecOptions,
    signal?: AbortSignal
): Promise<{
    execResult?: ExecResult
    error?: any
    durationMs: number
}> {
    return await semaphore.run(async () => {
        return await instrumentFn(`hog-exec`, async () => {
            return await yieldEventLoopIfNeeded('hog-exec', () => {
                const passedBefore = deadlineError(signal)
                if (passedBefore !== undefined) {
                    return { error: passedBefore, durationMs: 0 }
                }
                const result = execHogImmediate(bytecode, withinDeadline(options, signal))
                const passedDuring = deadlineError(signal)
                return passedDuring !== undefined ? { error: passedDuring, durationMs: result.durationMs } : result
            })
        })
    })
}

function withinDeadline(options: ExecOptions | undefined, signal: AbortSignal | undefined): ExecOptions | undefined {
    const remainingMs = deadlineRemainingMs(signal)
    if (remainingMs === undefined) {
        return options
    }
    return { ...options, timeout: Math.min(options?.timeout ?? DEFAULT_TIMEOUT_MS, Math.max(1, remainingMs)) }
}

export function execHogImmediate(
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
                regex: {
                    match: (regex, str) => createTrackedRE2(regex, undefined, 'hog-exec:regex.match').test(str),
                    extract: (regex, str) => {
                        const match = createTrackedRE2(regex, undefined, 'hog-exec:regex.extract').exec(str)
                        if (!match) {
                            return ''
                        }
                        return match.length > 1 ? (match[1] ?? '') : (match[0] ?? '')
                    },
                },
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
