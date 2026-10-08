/**
 * Attribute values arrive JSON-encoded from capture (`any_value_to_json`): a string
 * attribute is stored as `"error"` (with quotes), a number as `123`. The ClickHouse
 * sink decodes string values with `JSONExtractString`, so that is what users see in
 * the Logs UI. Every ingestion-time consumer of the attribute maps (transformations,
 * drop-rule matching, metric-rule tallying) must see the same decoded values —
 * otherwise `record.attributes['level'] == 'error'` silently never matches.
 *
 * Uses JSON.parse directly, not the instrumented parseJSON wrapper: this runs per
 * attribute per record at 100k+ records/s, and the wrapper's two performance.now()
 * calls plus a Prometheus Summary.observe per parse cost more than the parse itself.
 */
export function decodeLogAttributeValue(value: string): string {
    if (value.length >= 2 && value.startsWith('"') && value.endsWith('"')) {
        // A quoted string whose interior has no backslash and no quote is escape-free
        // valid JSON, so the decode is a plain slice and JSON.parse would return the
        // identical string. Anything else ('"a"b"', escapes) falls through to
        // JSON.parse to preserve its exact accept/reject behavior.
        const interior = value.slice(1, -1)
        if (!interior.includes('\\') && !interior.includes('"')) {
            return interior
        }
        try {
            // oxlint-disable-next-line eslint-js/no-restricted-syntax
            const parsed = JSON.parse(value)
            if (typeof parsed === 'string') {
                return parsed
            }
        } catch {
            // Not valid JSON — treat as a plain string
        }
    }
    return value
}

/**
 * Inverse of `decodeLogAttributeValue` for values written back onto the record:
 * plain strings are JSON-encoded so the ClickHouse sink's `JSONExtractString`
 * surfaces them; values that are already valid JSON (numbers, booleans, objects,
 * pre-encoded strings) pass through unchanged.
 */
export function encodeLogAttributeValue(value: string): string {
    try {
        // oxlint-disable-next-line eslint-js/no-restricted-syntax
        JSON.parse(value)
        return value
    } catch {
        return JSON.stringify(value)
    }
}
