/**
 * Lightweight async-function instrumentation: wraps a `() => Promise<T>` in
 * a structured-log timer so call sites get latency tracing without inline
 * `Date.now()` arithmetic everywhere.
 *
 * Modelled on `nodejs/src/common/tracing/tracing-utils.ts` `instrumentFn`
 * but stripped of prometheus + opentelemetry — agent-shared can't pull in
 * those deps without bloating every service that consumes it. Each call
 * logs `{ key, ms, ok }` (plus any caller-supplied context) at the end;
 * exceptions are re-thrown after logging.
 *
 * Use this for any async step that's load-bearing to user-facing latency:
 * the freeze pipeline (list, derive, validate, freeze), session start
 * (load revision, open MCPs, build dispatcher), etc.
 *
 * @example
 * ```ts
 * const sha = await instrument({ key: 'bundle.freeze', log, context: { rev } },
 *     () => bundles.freeze(rev, entries),
 * )
 * ```
 *
 * @example with caller-supplied context
 * ```ts
 * await instrument({ key: 'derive', log, context: { files: entries.length } },
 *     () => deriveAndPersistSpec({ ... }),
 * )
 * ```
 */

import type { Logger } from './logger'

export interface InstrumentOptions {
    /** Stable identifier shown in the log line. Convention: `subsystem.step`. */
    key: string
    /** Pino-shaped logger; the structured fields go on its `info`/`error` calls. */
    log: Logger
    /** Extra structured fields merged into the log line. */
    context?: Record<string, unknown>
    /** Optional ms threshold — log at `info` if exceeded, `debug` otherwise.
     *  Default 100ms (anything sub-100ms is too noisy to log at info). */
    slowThresholdMs?: number
}

export async function instrument<T>(opts: InstrumentOptions, fn: () => Promise<T>): Promise<T> {
    const t0 = Date.now()
    try {
        const result = await fn()
        const ms = Date.now() - t0
        const slow = ms >= (opts.slowThresholdMs ?? 100)
        const fields = { key: opts.key, ms, ok: true, ...opts.context }
        if (slow) {
            opts.log.info(fields, 'instrument')
        } else {
            opts.log.debug(fields, 'instrument')
        }
        return result
    } catch (err) {
        const ms = Date.now() - t0
        opts.log.error(
            {
                key: opts.key,
                ms,
                ok: false,
                err: err instanceof Error ? err.message : String(err),
                ...opts.context,
            },
            'instrument'
        )
        throw err
    }
}
