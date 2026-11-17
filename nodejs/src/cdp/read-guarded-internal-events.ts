import { CyclotronJobInvocation, CyclotronJobInvocationHogFunction } from './types'

// Mirror of the keys of `INTERNAL_EVENT_READ_SCOPES` in `products/cdp/backend/internal_events.py`. Keep the two in
// sync. A destination on one of these events handles product data behind its own read access, while log lines and
// invocation error messages are readable with plain project query access, so their text is not stored.
export const READ_GUARDED_INTERNAL_EVENTS: ReadonlySet<string> = new Set(['$signals_report_ready'])

export const HIDDEN_OUTPUT_MESSAGE =
    'Output hidden. This destination handles data that needs its own read access, so its log text is not stored.'

/** Return whether an invocation runs on a read-guarded internal event, so its logs and errors must not keep text. */
export function hidesInvocationOutput(invocation: CyclotronJobInvocation): boolean {
    if (!('hogFunction' in invocation)) {
        return false
    }
    const eventName = (invocation as CyclotronJobInvocationHogFunction).state?.globals?.event?.event
    return typeof eventName === 'string' && READ_GUARDED_INTERNAL_EVENTS.has(eventName)
}
