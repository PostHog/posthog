/**
 * Lossy ingestion scrub: replace matches with PII_REDACTED ({{REDACTED}}). The log `body` is **not** parsed as
 * JSON; RE2-backed patterns run on the raw UTF-8 string (emails and similar literals inside serialized JSON still
 * match). Rules: Bearer-shaped tokens, Stripe `sk_*` keys, email addresses. Attribute and resource maps still use
 * sensitive-key substring checks (full value redaction) plus the same pattern scrub on other values. Map values are
 * JSON-string cells (JSON.stringify) so ClickHouse JSONExtractString matches Rust OTLP encoding.
 *
 * **Not guaranteed:** secrets only discoverable by JSON object keys inside `body` (no tree walk), values only in
 * JSON number/boolean leaves. PAN-like digit runs are **not** redacted (lite path).
 *
 * The match rules use RE2 (via createTrackedRE2) for linear-time matching and consistency with other nodejs regex
 * paths; patterns use ASCII-explicit classes so behavior stays stable under node-re2’s Unicode mode.
 */
import { parseJSON } from '../utils/json-parse'
import { createTrackedRE2 } from '../utils/tracked-re2'
import type { LogRecord } from './log-record-avro'

export const PII_REDACTED = '{{REDACTED}}'

/** Substrings matched case-insensitively against attribute map keys (exported for tests). */
export const SENSITIVE_KEY_SUBSTRINGS = [
    'password',
    'secret',
    'token',
    'authorization',
    'cookie',
    'credential',
    'apikey',
    'api_key',
    'access_token',
    'refresh_token',
    'bearer',
    'email',
] as const

/** RFC 6750-ish token chars (ASCII only); body then optional `=` padding, case-insensitive `Bearer`. */
const BEARER_HEADER_RE = createTrackedRE2('Bearer\\s+[-A-Za-z0-9._~+/]+=*', 'gi', 'log-pii-scrub:bearer')
const STRIPE_SECRET_KEY_RE = createTrackedRE2('\\bsk_(?:live|test)_[a-zA-Z0-9]{20,}\\b', 'g', 'log-pii-scrub:stripe')
const EMAIL_RE = createTrackedRE2('\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}\\b', 'g', 'log-pii-scrub:email')

/** True when the attribute key contains a known sensitive substring (case-insensitive). */
export function isSensitiveAttributeKey(key: string): boolean {
    const lower = key.toLowerCase()
    return SENSITIVE_KEY_SUBSTRINGS.some((s) => lower.includes(s))
}

/** True when `value` is a JSON document consisting of a single string (OTLP serde_json string cell). */
function looksLikeJsonStringCell(value: string): boolean {
    return value.length >= 2 && value[0] === '"' && value[value.length - 1] === '"'
}

/** Rust OTLP path stores string attrs as serde_json string values; unwrap one JSON string layer if present. */
export function unwrapAttributeCell(value: string): string {
    if (!looksLikeJsonStringCell(value)) {
        return value
    }
    try {
        const parsed = parseJSON(value)
        if (typeof parsed === 'string') {
            return parsed
        }
    } catch {
        // not valid JSON — treat whole cell as semantic text
    }
    return value
}

/** Match Rust serde_json::Value::String(s).to_string() / CH kafka_logs_avro_mv JSONExtractString expectations. */
export function encodeAttributeCell(semantic: string): string {
    return JSON.stringify(semantic)
}

/** Apply regex-based redaction to a single string (log line, attribute value, field text, etc.). */
export function scrubPlainString(input: string): string {
    let s = input.replace(BEARER_HEADER_RE, `Bearer ${PII_REDACTED}`)
    s = s.replace(STRIPE_SECRET_KEY_RE, PII_REDACTED)
    s = s.replace(EMAIL_RE, PII_REDACTED)
    return s
}

/** Pattern-scrub `body` as a single string (no JSON parse). */
function scrubBodyField(record: LogRecord): void {
    if (record.body == null) {
        return
    }
    record.body = scrubPlainString(record.body)
}

/** Copy string map: full redaction for sensitive keys, else pattern-scrub semantic values; CH-safe JSON cells. */
function scrubStringMap(map: Record<string, string> | null): Record<string, string> | null {
    if (map == null) {
        return null
    }
    const out: Record<string, string> = {}
    for (const [key, value] of Object.entries(map)) {
        if (isSensitiveAttributeKey(key)) {
            out[key] = encodeAttributeCell(PII_REDACTED)
        } else {
            const semantic = unwrapAttributeCell(value)
            out[key] = encodeAttributeCell(scrubPlainString(semantic))
        }
    }
    return out
}

/** Mutate record in place: body, attributes, resource_attributes, and common string metadata fields. */
export function scrubLogRecord(record: LogRecord): void {
    scrubBodyField(record)
    record.attributes = scrubStringMap(record.attributes)
    record.resource_attributes = scrubStringMap(record.resource_attributes)
    if (record.service_name) {
        record.service_name = scrubPlainString(record.service_name)
    }
    if (record.instrumentation_scope) {
        record.instrumentation_scope = scrubPlainString(record.instrumentation_scope)
    }
    if (record.severity_text) {
        record.severity_text = scrubPlainString(record.severity_text)
    }
    if (record.event_name) {
        record.event_name = scrubPlainString(record.event_name)
    }
}
