/**
 * Process-level safety net. Every long-running service should call
 * `installProcessHandlers(log)` exactly once in its `index.ts` so a stray
 * unhandled rejection or uncaught exception is logged with structure before
 * the process either continues (rejections) or exits (exceptions).
 *
 * Without these, an unhandled async rejection in an express route bubbles
 * past express's default handler and ends up on Node's default printer
 * (unformatted stack trace to stderr), and in newer Node versions
 * (>=15 unless `--unhandled-rejections=warn`) it crashes the process.
 *
 * Behavior:
 *   - `unhandledRejection`  → log at `error`, do NOT exit. We'd rather keep
 *                             serving healthy traffic than crash on one
 *                             stray promise. The bug still surfaces in logs.
 *   - `uncaughtException`   → log at `fatal`, then exit(1). The Node docs
 *                             explicitly say the process is in an undefined
 *                             state after this; a clean restart is safer.
 *
 * Call once per process, near the top of `main()`.
 */

import type { Logger } from './logger'

export function installProcessHandlers(log: Logger): void {
    process.on('unhandledRejection', (reason: unknown) => {
        const err = reason instanceof Error ? reason : new Error(String(reason))
        log.error({ err: err.message, stack: err.stack }, 'unhandledRejection')
    })
    process.on('uncaughtException', (err: Error) => {
        log.fatal({ err: err.message, stack: err.stack }, 'uncaughtException')
        // The Node docs are clear: continuing after this is unsafe.
        // Give the logger a tick to flush, then exit.
        setTimeout(() => process.exit(1), 100).unref()
    })
}
