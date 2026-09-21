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
 * The parameter is a structural type rather than the logger module's Logger so this file
 * compiles standalone for the child-process regression test.
 */
export function installUnhandledRejectionGuard(log: RejectionLogger): void {
    process.on('unhandledRejection', (reason) => {
        log.error({ err: reason }, 'unhandled promise rejection (kept alive)')
    })
}
