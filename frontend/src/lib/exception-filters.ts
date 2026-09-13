import { BeforeSendFn, CaptureResult } from 'posthog-js'

interface ReportedException {
    type?: string
    value?: string
    mechanism?: { handled?: boolean }
}

function isUnhandledAbort(exception: ReportedException): boolean {
    return (
        exception.mechanism?.handled === false &&
        (exception.type === 'AbortError' || (exception.value ?? '').startsWith('AbortError'))
    )
}

/**
 * Drops an exception capture that only reports a cancellation the app asked for.
 *
 * An `AbortError` that reaches error tracking with no handler always comes from our own teardown:
 * a disposable that pauses when the tab goes hidden, a logic that unmounts, a request that a later
 * one supersedes. Firefox raises one for the response body of every streaming fetch we abort, so
 * `api.stream` files each hidden tab as an exception. Each release files it again, because the
 * fingerprint follows the line number in `api.ts`.
 *
 * An abort that a caller reports on purpose carries `handled: true`, so it stays. The rule covers
 * every unhandled abort, not only the stream one, because the capture holds no property that says
 * where the abort started. That is the same trade the app already makes elsewhere: an abort that
 * no caller waits on reports a cancellation, never a defect a reader can act on.
 */
export const dropUnhandledAbortExceptions: BeforeSendFn = (event: CaptureResult | null) => {
    if (event?.event !== '$exception') {
        return event
    }
    const exceptions: ReportedException[] | undefined = event.properties?.$exception_list
    if (!Array.isArray(exceptions) || exceptions.length === 0) {
        return event
    }
    return exceptions.every(isUnhandledAbort) ? null : event
}
