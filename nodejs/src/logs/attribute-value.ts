import { parseJSON } from '~/common/utils/json-parse'

/**
 * Attribute values arrive JSON-encoded from capture (`any_value_to_json`): a string
 * attribute is stored as `"error"` (with quotes), a number as `123`. The ClickHouse
 * sink decodes string values with `JSONExtractString`, so that is what users see in
 * the Logs UI. Every ingestion-time consumer of the attribute maps (transformations,
 * drop-rule matching, metric-rule tallying) must see the same decoded values —
 * otherwise `record.attributes['level'] == 'error'` silently never matches.
 */
export function decodeLogAttributeValue(value: string): string {
    if (value.length >= 2 && value.startsWith('"') && value.endsWith('"')) {
        try {
            const parsed = parseJSON(value)
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
        parseJSON(value)
        return value
    } catch {
        return JSON.stringify(value)
    }
}
