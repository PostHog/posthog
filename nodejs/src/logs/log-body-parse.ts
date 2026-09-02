import { parseJSON } from '~/common/utils/json-parse'

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

// JSON allows only these four characters between the start of the document and the value.
const isJsonWhitespace = (code: number): boolean => code === 0x20 || code === 0x09 || code === 0x0a || code === 0x0d

/**
 * True when the first non-whitespace character is one a JSON document can begin with:
 * `{`, `[`, `"`, `-`, a digit, or the first letter of `true`, `false`, or `null`.
 *
 * The set holds all eight starts on purpose. A `{`/`[` check would send top-level JSON strings
 * and bare scalars down the `invalid_json` branch, which changes the pattern they produce.
 */
function canStartJsonDocument(body: string): boolean {
    for (let index = 0; index < body.length; index++) {
        const code = body.charCodeAt(index)
        if (isJsonWhitespace(code)) {
            continue
        }
        return (
            code === 0x7b || // {
            code === 0x5b || // [
            code === 0x22 || // "
            code === 0x2d || // -
            (code >= 0x30 && code <= 0x39) || // 0-9
            code === 0x74 || // t, for true
            code === 0x66 || // f, for false
            code === 0x6e // n, for null
        )
    }
    return false
}

export function parseLogBodyForIngestion(body: string | null): LogBodyParseResult {
    if (body === null) {
        return { kind: 'empty' }
    }
    // Plaintext log lines are a large share of the traffic and every one of them makes `parseJSON`
    // build and throw an error. The scan reaches the same result without paying for the throw.
    if (!canStartJsonDocument(body)) {
        return { kind: 'invalid_json', raw: body }
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
