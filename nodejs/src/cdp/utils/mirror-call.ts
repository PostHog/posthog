import { logger } from '~/common/utils/logger'

import { instrumentFn } from '../../common/tracing/tracing-utils'

const DEFAULT_TIMEOUT_MS = 2000

/**
 * Wraps a Valkey mirror call so it can never affect the primary code path.
 *
 * - Real cancellation comes from `commandTimeout` on the shadow ioredis client
 *   (set in `createCdpValkeyShadowPools`), which aborts at the protocol level.
 *   The race below is a backstop — it stops the helper from awaiting beyond
 *   `timeoutMs` even if the underlying client misbehaves.
 * - Catches any error or timeout and logs it.
 * - Always resolves to `undefined`, so the result can be dropped into
 *   `Promise.all([...])` or `promiseScheduler.schedule(...)` alongside the
 *   primary call.
 * - Wrapped in `instrumentFn` so latency / errors surface in tracing under
 *   the `cdp.mirror.<label>` key.
 *
 */
export async function mirrorCall(
    label: string,
    call: () => Promise<unknown>,
    timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<void> {
    return instrumentFn({ key: `cdp.mirror.${label}`, sendException: false }, async () => {
        let timeoutId: NodeJS.Timeout | undefined
        try {
            const promise = call()
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
    })
}

/** Runs Redis and its Valkey shadow in parallel while keeping Redis authoritative. */
export async function mirrorCallWithPrimary<T>(
    label: string,
    primaryCall: () => Promise<T>,
    mirrorCallFactory: () => Promise<unknown>,
    timeoutMs?: number
): Promise<T> {
    const [primary] = await Promise.all([primaryCall(), mirrorCall(label, mirrorCallFactory, timeoutMs)])
    return primary
}
