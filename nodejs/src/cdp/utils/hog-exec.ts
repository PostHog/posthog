import crypto from 'crypto'

import { DEFAULT_TIMEOUT_MS, ExecOptions, ExecResult, exec } from '@posthog/hogvm'

import { instrumentFn } from '~/common/tracing/tracing-utils'

import { yieldEventLoopIfNeeded } from '../../utils/event-loop-yield'
import { createTrackedRE2 } from '../../utils/tracked-re2'
import { Semaphore } from './sempahore'

const semaphore = new Semaphore(1)

export async function execHog(
    bytecode: any,
    options?: ExecOptions
): Promise<{
    execResult?: ExecResult
    error?: any
    durationMs: number
}> {
    return await semaphore.run(async () => {
        return await instrumentFn(`hog-exec`, async () => {
            return await yieldEventLoopIfNeeded('hog-exec', () => execHogImmediate(bytecode, options))
        })
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
