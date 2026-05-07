import { parseJSON } from '../utils/json-parse'

/**
 * Single `parseJSON(record.body)` outcome for logs ingestion.
 * Branches match `extractJsonAttributesFromBody` and `scrubBodyField` so one parse can feed both.
 */
export type LogBodyParseResult =
    | { kind: 'empty' }
    | { kind: 'invalid_json'; raw: string }
    | { kind: 'json_object_or_array'; value: object }
    | { kind: 'json_string'; value: string }
    | { kind: 'json_primitive'; parsed: number | boolean | null }

export function parseLogBodyForIngestion(body: string | null): LogBodyParseResult {
    if (body === null) {
        return { kind: 'empty' }
    }
    try {
        const parsed = parseJSON(body)
        if (parsed !== null && typeof parsed === 'object') {
            return { kind: 'json_object_or_array', value: parsed as object }
        }
        if (typeof parsed === 'string') {
            return { kind: 'json_string', value: parsed }
        }
        return { kind: 'json_primitive', parsed: parsed as number | boolean | null }
    } catch {
        return { kind: 'invalid_json', raw: body }
    }
}
