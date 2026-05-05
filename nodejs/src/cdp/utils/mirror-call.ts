import { logger } from '../../utils/logger'

const DEFAULT_TIMEOUT_MS = 1000

/**
 * Wraps a Valkey mirror call so it can never affect the primary code path.
 *
 * - Stops awaiting after `timeoutMs` (the underlying request continues in the
 *   background until it settles or the connection drops; we just don't block on it).
 * - Catches any error or timeout and logs it.
 * - Always resolves to `undefined`, so the result can be dropped into
 *   `Promise.all([...])` or `promiseScheduler.schedule(...)` alongside the
 *   primary call.
 *
 * The `call` arg returns `Promise<unknown> | undefined` so the common pattern
 * of `() => this.fooMirror?.bar(args)` works directly: when the mirror is null
 * the inner expression evaluates to undefined and the helper short-circuits.
 */
export async function mirrorCall(
    label: string,
    call: () => Promise<unknown> | undefined,
    timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<void> {
    let timeoutId: NodeJS.Timeout | undefined
    try {
        const promise = call()
        if (!promise) {
            return
        }
        await Promise.race([
            promise,
            new Promise<never>((_, reject) => {
                timeoutId = setTimeout(
                    () => reject(new Error(`mirror call timed out after ${timeoutMs}ms`)),
                    timeoutMs
                )
            }),
        ])
    } catch (err) {
        logger.warn('🪞', `[mirror:${label}] failed`, { err: String(err) })
    } finally {
        if (timeoutId) {
            clearTimeout(timeoutId)
        }
    }
}
