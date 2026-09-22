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
 * The parameters are structural types rather than the logger and metrics modules so this
 * file compiles standalone for the child-process regression test.
 */
export function installUnhandledRejectionGuard(
    log: RejectionLogger,
    onSuppressed: () => void = () => {}
): void {
    const WINDOW_MS = 60_000
    const MAX_SUPPRESSED = 50

    const suppressedAt: number[] = []
    const listener = (reason: unknown): void => {
        onSuppressed()
        const now = Date.now()
        suppressedAt.push(now)
        while (suppressedAt.length > 0 && now - suppressedAt[0] > WINDOW_MS) {
            suppressedAt.shift()
        }
        if (suppressedAt.length > MAX_SUPPRESSED) {
            log.error({ err: reason, suppressed: suppressedAt.length }, 'unhandled rejection flood, disarming guard')
            process.off('unhandledRejection', listener)
            return
        }
        log.error({ err: reason }, 'unhandled promise rejection (kept alive)')
    }
    process.on('unhandledRejection', listener)
}
