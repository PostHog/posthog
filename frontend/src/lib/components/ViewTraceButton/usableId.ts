/**
 * A trace or span id in the form the events hold it, or null when the row carries none.
 *
 * Spans read their ids back as uppercase hex while the SDKs write them lowercase. An id of all
 * zeros is OpenTelemetry's "no id" sentinel, and it arrives as a string like any other, so a
 * caller that only checks for a value would match every uninstrumented row to it.
 */
export function usableId(value: string | null | undefined): string | null {
    if (!value) {
        return null
    }
    const normalized = value.toLowerCase()
    return /^0+$/.test(normalized) ? null : normalized
}
