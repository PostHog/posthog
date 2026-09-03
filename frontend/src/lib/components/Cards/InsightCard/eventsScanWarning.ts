import type { EventsScanWarning, HogQLQueryResponse } from '~/queries/schema/schema-general'

/** The events scan warnings from a query response, joined into one message for a tooltip or banner. */
export function eventsScanWarningMessage(warnings: HogQLQueryResponse['warnings'] | null | undefined): string | null {
    const scanWarnings = (warnings ?? []).filter(
        (warning): warning is EventsScanWarning => warning.type === 'events_scan'
    )
    return scanWarnings.length > 0 ? scanWarnings.map((warning) => warning.message).join(' ') : null
}
