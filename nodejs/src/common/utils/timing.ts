import { timeoutGuard } from './db/utils'

export async function asyncTimeoutGuard(
    options: {
        message: string
        context?: Record<string, any>
        timeout?: number
    },
    fn: () => Promise<any>
): Promise<any> {
    const timeout = timeoutGuard(options.message, options.context, options.timeout)

    try {
        await fn()
    } finally {
        clearTimeout(timeout)
    }
}

/**
 * Race `p` against a timeout. Unlike `Promise.race([p, sleep(ms).then(...)])`, this clears
 * the timer when `p` settles first so we don't leak a pending setTimeout into the event loop.
 */
export function raceWithTimeout<T>(p: Promise<T>, ms: number): Promise<{ value?: T; timedOut: boolean }> {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => resolve({ timedOut: true }), ms)
        p.then(
            (v) => {
                clearTimeout(timer)
                resolve({ value: v, timedOut: false })
            },
            (e) => {
                clearTimeout(timer)
                reject(e)
            }
        )
    })
}
