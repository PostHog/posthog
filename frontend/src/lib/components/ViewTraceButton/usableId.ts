/**
 * A trace or span id in the form the events hold it, or null when the row carries none.
 *
 * Spans read their ids back as uppercase hex while the SDKs write them lowercase. An id of all
 * zeros is OpenTelemetry's "no id" sentinel, and it arrives as a string like any other, so a
 * caller that only checks for a value would match every uninstrumented row to it.
 * Stored trace and span ids are always whole bytes of hex, so any other value is null too. Event
 * properties such as `$trace_id` accept any string, and callers put the id into URLs and API paths.
 */
export function usableId(value: string | null | undefined): string | null {
    if (!value) {
        return null
    }
    const normalized = value.toLowerCase()
    return /^(?:[0-9a-f]{2})+$/.test(normalized) && !/^0+$/.test(normalized) ? normalized : null
}
