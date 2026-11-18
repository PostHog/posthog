type RejectionLogger = {
    error: (fields: Record<string, unknown>, message: string) => void
}

/**
 * Keep the process alive when a promise no caller owns rejects.
 *
 * Closing a page to abort a capture rejects whatever CDP call puppeteer-capture has in
 * flight (TargetCloseError). That rejection belongs to no promise the worker awaits, so
 * Node treats it as unhandled and terminates the process, which kills every in-flight
 * rasterization on the pod. The activity already fails with CAPTURE_ABORTED on its own;
 * the rejection carries nothing recoverable, so log it and keep the worker alive.
 *
 * The guard is bounded: a worker that rejects without pause is genuinely broken, and
 * staying alive would leave a pod that fails every activity. Past the suppression bound
 * the guard removes itself, and the next rejection terminates the process as before,
 * so an unbounded failure still surfaces as a restart.
 *
 * The parameters are structural types rather than the logger and metrics modules, and
 * the clock is injectable, so this file compiles standalone for the regression test.
 */
export function installUnhandledRejectionGuard(
    log: RejectionLogger,
    onSuppressed: () => void = () => {},
    now: () => number = Date.now
): void {
    const WINDOW_MS = 60_000
    const MAX_SUPPRESSED = 50

    const suppressedAt: number[] = []
    const listener = (reason: unknown): void => {
        onSuppressed()
        const timestamp = now()
        suppressedAt.push(timestamp)
        while (suppressedAt.length > 0 && timestamp - suppressedAt[0] > WINDOW_MS) {
            suppressedAt.shift()
        }
        if (suppressedAt.length > MAX_SUPPRESSED) {
            log.error({ err: reason }, 'unhandled rejection flood, disarming guard')
            process.off('unhandledRejection', listener)
            return
        }
        log.error({ err: reason }, 'unhandled promise rejection (kept alive)')
    }
    process.on('unhandledRejection', listener)
}
