import type { EventsScanWarning, HogQLQueryResponse } from '~/queries/schema/schema-general'

/** The distinct events scan messages from a query response.
 *
 * The backend reports one finding per read of `events`, and a message names the missing limit
 * without saying which read it belongs to. A query that reads `events` twice without a limit, such
 * as a self-join or a CTE plus its outer select, therefore repeats the same sentence. Only the
 * `start` and `end` offsets tell the copies apart, and no surface that renders these messages shows
 * them, so drop the repeats here rather than in the response.
 */
export function eventsScanWarningMessages(warnings: HogQLQueryResponse['warnings'] | null | undefined): string[] {
    const scanWarnings = (warnings ?? []).filter(
        (warning): warning is EventsScanWarning => warning.type === 'events_scan'
    )
    return [...new Set(scanWarnings.map((warning) => warning.message))]
}

/** The events scan warnings from a query response, joined into one message for a tooltip or banner. */
export function eventsScanWarningMessage(warnings: HogQLQueryResponse['warnings'] | null | undefined): string | null {
    const messages = eventsScanWarningMessages(warnings)
    return messages.length > 0 ? messages.join(' ') : null
}
