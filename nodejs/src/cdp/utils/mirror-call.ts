import { isDeepStrictEqual } from 'node:util'
import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'

import { instrumentFn } from '../../common/tracing/tracing-utils'

const DEFAULT_TIMEOUT_MS = 2000
const mismatchWarningLogged = new Set<string>()

const mirrorOperationsTotal = new Counter({
    name: 'cdp_valkey_mirror_operations_total',
    help: 'CDP Redis-to-Valkey mirror operations by operation and outcome.',
    labelNames: ['operation', 'outcome'],
})

type MirrorOutcome<T> = { status: 'completed'; value: T } | { status: 'skipped' } | { status: 'failed' }

async function runMirrorCall<T>(
    label: string,
    call: () => Promise<T> | undefined,
    timeoutMs: number
): Promise<MirrorOutcome<T>> {
    let timeoutId: NodeJS.Timeout | undefined
    try {
        const promise = call()
        if (!promise) {
            mirrorOperationsTotal.labels({ operation: label, outcome: 'skipped' }).inc()
            return { status: 'skipped' }
        }
        const value = await Promise.race([
            promise,
            new Promise<never>((_, reject) => {
                timeoutId = setTimeout(() => reject(new Error(`mirror call timed out after ${timeoutMs}ms`)), timeoutMs)
            }),
        ])
        return { status: 'completed', value }
    } catch (err) {
        mirrorOperationsTotal.labels({ operation: label, outcome: 'failed' }).inc()
        logger.warn('🪞', `[mirror:${label}] failed`, { err: String(err) })
        return { status: 'failed' }
    } finally {
        if (timeoutId) {
            clearTimeout(timeoutId)
        }
    }
}

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
 * The `call` arg returns `Promise<unknown> | undefined` so the common pattern
 * of `() => this.fooMirror?.bar(args)` works directly: when the mirror is null
 * the inner expression evaluates to undefined and the helper short-circuits.
 */
export async function mirrorCall(
    label: string,
    call: () => Promise<unknown> | undefined,
    timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<void> {
    return instrumentFn({ key: `cdp.mirror.${label}`, sendException: false }, async () => {
        const outcome = await runMirrorCall(label, call, timeoutMs)
        if (outcome.status === 'completed') {
            mirrorOperationsTotal.labels({ operation: label, outcome: 'completed' }).inc()
        }
    })
}

/**
 * Runs an authoritative Redis read and its Valkey mirror in parallel, returning
 * the Redis result while recording whether Valkey returned equivalent data.
 */
export async function mirrorCompare<T>(
    label: string,
    primaryCall: () => Promise<T>,
    mirrorCallFactory: () => Promise<T> | undefined,
    isEquivalent: (primary: T, mirror: T) => boolean = isDeepStrictEqual,
    timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<T> {
    const primaryPromise = primaryCall()
    const mirrorPromise = instrumentFn({ key: `cdp.mirror.${label}`, sendException: false }, () =>
        runMirrorCall(label, mirrorCallFactory, timeoutMs)
    )
    const [primary, mirror] = await Promise.all([primaryPromise, mirrorPromise])

    if (mirror.status === 'completed') {
        const outcome = isEquivalent(primary, mirror.value) ? 'matched' : 'mismatched'
        mirrorOperationsTotal.labels({ operation: label, outcome }).inc()
        if (outcome === 'mismatched' && !mismatchWarningLogged.has(label)) {
            mismatchWarningLogged.add(label)
            logger.warn('🪞', `[mirror:${label}] result mismatch`)
        }
    }

    return primary
}
