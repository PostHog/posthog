import { isDeepStrictEqual } from 'node:util'
import { Counter } from 'prom-client'

import { logger } from '~/common/utils/logger'

import { instrumentFn } from '../../common/tracing/tracing-utils'

const DEFAULT_TIMEOUT_MS = 2000
const mismatchWarningLogged = new Set<string>()

/**
 * CDP features whose Redis calls also run against Valkey.
 *
 * Writes always go to both stores. Reads come from Redis until a feature is named in
 * `CDP_VALKEY_READ_FEATURES`, which flips that feature — and only that feature — over to
 * Valkey. Listed roughly in the order they are safe to flip: the entries near the top
 * back caches and metrics, the ones near the bottom decide whether an invocation runs.
 */
export const MIRROR_FEATURES = [
    'hog-flow-duplicate-observer',
    'hog-function-rate-limiter',
    'hog-masker',
    'hog-flow-rate-limiter',
    'hog-watcher',
] as const

export type MirrorFeature = (typeof MIRROR_FEATURES)[number]

/** `<feature>.<operation>`; the operation half is free-form and only feeds metrics and logs. */
export type MirrorLabel = `${MirrorFeature}.${string}`

type Store = 'redis' | 'valkey'

const mirrorOperationsTotal = new Counter({
    name: 'cdp_valkey_mirror_operations_total',
    // `source` is the store the feature reads from, so `failed` means the *other* store's call failed.
    help: 'CDP Redis/Valkey dual-store operations by operation, read source and outcome.',
    labelNames: ['operation', 'source', 'outcome'],
})

// Process-wide because the helpers below are free functions called from a dozen services that
// have no other reason to carry config. Set once per process from `createCdpCoreServices`.
let valkeyReadFeatures: ReadonlySet<MirrorFeature> = new Set()

/**
 * Parses the comma-separated `CDP_VALKEY_READ_FEATURES` value. `*` selects every feature.
 *
 * Throws on an unrecognised name: a typo would otherwise leave reads quietly on Redis while
 * the deploy looks like it migrated the feature.
 */
export function parseValkeyReadFeatures(raw: string): Set<MirrorFeature> {
    const names = raw
        .split(',')
        .map((name) => name.trim())
        .filter(Boolean)

    if (names.includes('*')) {
        return new Set(MIRROR_FEATURES)
    }

    const unknown = names.filter((name) => !(MIRROR_FEATURES as readonly string[]).includes(name))
    if (unknown.length > 0) {
        throw new Error(
            `CDP_VALKEY_READ_FEATURES contains unknown feature(s): ${unknown.join(', ')}. Known features: ${MIRROR_FEATURES.join(', ')}`
        )
    }

    return new Set(names as MirrorFeature[])
}

export function configureValkeyReads(raw: string): void {
    valkeyReadFeatures = parseValkeyReadFeatures(raw)
    logger.info(
        '🪞',
        `[dual-store] reading from valkey: ${valkeyReadFeatures.size > 0 ? [...valkeyReadFeatures].join(', ') : '<none, all reads from redis>'}`
    )
}

export function readSourceFor(label: MirrorLabel): Store {
    const feature = label.split('.')[0] as MirrorFeature
    return valkeyReadFeatures.has(feature) ? 'valkey' : 'redis'
}

type SecondaryOutcome<T> = { status: 'completed'; value: T } | { status: 'failed' }

/**
 * Runs the non-read store's call so it can never affect the primary code path.
 *
 * - Real cancellation comes from `commandTimeout` on the shadow ioredis client
 *   (set in `createCdpValkeyShadowPools`), which aborts at the protocol level.
 *   The race below is a backstop — it stops the helper from awaiting beyond
 *   `timeoutMs` even if the underlying client misbehaves.
 * - Catches any error or timeout and logs it, so it never rejects.
 * - Wrapped in `instrumentFn` so latency / errors surface in tracing under
 *   the `cdp.mirror.<label>` key.
 */
async function runSecondary<T>(
    label: MirrorLabel,
    source: Store,
    call: () => Promise<T>,
    timeoutMs: number
): Promise<SecondaryOutcome<T>> {
    return instrumentFn({ key: `cdp.mirror.${label}`, sendException: false }, async () => {
        let timeoutId: NodeJS.Timeout | undefined
        try {
            const value = await Promise.race([
                call(),
                new Promise<never>((_, reject) => {
                    timeoutId = setTimeout(
                        () => reject(new Error(`secondary call timed out after ${timeoutMs}ms`)),
                        timeoutMs
                    )
                }),
            ])
            return { status: 'completed', value } as const
        } catch (err) {
            mirrorOperationsTotal.labels({ operation: label, source, outcome: 'failed' }).inc()
            logger.warn('🪞', `[mirror:${label}] secondary store failed`, { err: String(err) })
            return { status: 'failed' } as const
        } finally {
            if (timeoutId) {
                clearTimeout(timeoutId)
            }
        }
    })
}

/** Splits the two calls into the one whose result we use and the one we only observe. */
function order<T>(
    label: MirrorLabel,
    redisCall: () => Promise<T>,
    valkeyCall: () => Promise<T>
): { source: Store; primary: () => Promise<T>; secondary: () => Promise<T> } {
    const source = readSourceFor(label)
    return source === 'valkey'
        ? { source, primary: valkeyCall, secondary: redisCall }
        : { source, primary: redisCall, secondary: valkeyCall }
}

/**
 * Runs a read against both stores in parallel, returning the result from whichever store this
 * feature currently reads from and recording whether the other returned equivalent data.
 *
 * The read source's errors propagate to the caller; the other store's are swallowed.
 */
export async function dualRead<T>(
    label: MirrorLabel,
    redisCall: () => Promise<T>,
    valkeyCall: () => Promise<T>,
    isEquivalent: (primary: T, secondary: T) => boolean = isDeepStrictEqual,
    timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<T> {
    const { source, primary, secondary } = order(label, redisCall, valkeyCall)

    const primaryPromise = primary()
    const secondaryPromise = runSecondary(label, source, secondary, timeoutMs)
    const [primaryResult, secondaryResult] = await Promise.all([primaryPromise, secondaryPromise])

    if (secondaryResult.status === 'completed') {
        // `isEquivalent` is caller-supplied and indexes into the secondary payload, so a shape
        // the comparator does not expect throws here — outside runSecondary's guard. Treat
        // that as a mismatch rather than letting it reject the primary result.
        let outcome: 'matched' | 'mismatched'
        try {
            outcome = isEquivalent(primaryResult, secondaryResult.value) ? 'matched' : 'mismatched'
        } catch (err) {
            outcome = 'mismatched'
            logger.warn('🪞', `[mirror:${label}] comparison threw`, { err: String(err) })
        }
        mirrorOperationsTotal.labels({ operation: label, source, outcome }).inc()
        if (outcome === 'mismatched' && !mismatchWarningLogged.has(label)) {
            mismatchWarningLogged.add(label)
            logger.warn('🪞', `[mirror:${label}] result mismatch`)
        }
    }

    return primaryResult
}

/**
 * Writes to both stores in parallel.
 *
 * Failures on the store this feature reads from propagate to the caller, because they change
 * what the next read decides. Failures on the other store are logged and counted only — that
 * data is not being read, so a gap in it cannot affect behaviour.
 */
export async function dualWrite(
    label: MirrorLabel,
    redisCall: () => Promise<unknown>,
    valkeyCall: () => Promise<unknown>,
    timeoutMs: number = DEFAULT_TIMEOUT_MS
): Promise<void> {
    const { source, primary, secondary } = order(label, redisCall, valkeyCall)

    const [, secondaryResult] = await Promise.all([primary(), runSecondary(label, source, secondary, timeoutMs)])

    if (secondaryResult.status === 'completed') {
        mirrorOperationsTotal.labels({ operation: label, source, outcome: 'completed' }).inc()
    }
}
