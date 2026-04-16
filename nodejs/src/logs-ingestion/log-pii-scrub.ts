/**
 * Lossy ingestion scrub: replace matches with PII_REDACTED ({{REDACTED}}). Plain text applies Bearer-token,
 * Stripe sk_*-shaped, email, and Luhn-valid 13–19 digit (card-like) patterns. JSON bodies are parsed when possible
 * and scrubbed recursively (object keys use the same sensitive-key substrings as attribute maps); opaque bodies get
 * plain rules only. Attribute maps redact the whole value on sensitive
 * key substrings, otherwise pattern-scrub values. Map values are JSON-string cells (JSON.stringify) so ClickHouse
 * JSONExtractString matches Rust OTLP encoding. Misses: secrets without those shapes, digit runs that fail Luhn,
 * keys outside the sensitive substring list (those values still get plain-text patterns only).
 *
 * The four main match rules use RE2 (via createTrackedRE2) for linear-time matching and consistency with other
 * nodejs regex paths; patterns use ASCII-explicit classes so behavior stays stable under node-re2’s Unicode mode.
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
/** 13–19 ASCII digits; optional single space or hyphen between digit groups (no nested quantifier over digit class). */
const CARD_LIKE_RE = createTrackedRE2('\\b[0-9](?:[- ]?[0-9]){12,18}\\b', 'g', 'log-pii-scrub:card')

/** True when the attribute key contains a known sensitive substring (case-insensitive). */
export function isSensitiveAttributeKey(key: string): boolean {
    const lower = key.toLowerCase()
    return SENSITIVE_KEY_SUBSTRINGS.some((s) => lower.includes(s))
}

/** Rust OTLP path stores string attrs as serde_json string values; unwrap one JSON string layer if present. */
export function unwrapAttributeCell(value: string): string {
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

/** Luhn checksum for filtering card-like digit runs before redaction. */
function luhnValid(digits: string): boolean {
    let sum = 0
    let alt = false
    for (let i = digits.length - 1; i >= 0; i--) {
        const d = parseInt(digits.charAt(i), 10)
        if (Number.isNaN(d)) {
            return false
        }
        let v = d
        if (alt) {
            v *= 2
            if (v > 9) {
                v -= 9
            }
        }
        sum += v
        alt = !alt
    }
    return sum % 10 === 0
}

/** Apply regex-based redaction to a single string (log line, attribute value, field text, etc.). */
export function scrubPlainString(input: string): string {
    let s = input.replace(BEARER_HEADER_RE, `Bearer ${PII_REDACTED}`)
    s = s.replace(STRIPE_SECRET_KEY_RE, PII_REDACTED)
    s = s.replace(EMAIL_RE, PII_REDACTED)
    s = s.replace(CARD_LIKE_RE, (match) => {
        const digits = match.replace(/\D/g, '')
        if (digits.length >= 13 && digits.length <= 19 && luhnValid(digits)) {
            return PII_REDACTED
        }
        return match
    })
    return s
}

/** Walk parsed JSON: scrub strings, recurse arrays and objects; leave numbers/bools/null unchanged. */
function scrubJsonValue(value: unknown): unknown {
    if (typeof value === 'string') {
        return scrubPlainString(value)
    }
    if (Array.isArray(value)) {
        return value.map(scrubJsonValue)
    }
    if (value !== null && typeof value === 'object') {
        const out: Record<string, unknown> = {}
        for (const [k, v] of Object.entries(value)) {
            out[k] = isSensitiveAttributeKey(k) ? PII_REDACTED : scrubJsonValue(v)
        }
        return out
    }
    return value
}

/** If body is JSON object/array, scrub nested strings and re-serialize; if invalid JSON, scrub as plain text. */
function scrubBodyField(record: LogRecord): void {
    if (record.body == null) {
        return
    }
    const body = record.body
    try {
        const parsed = parseJSON(body)
        if (parsed !== null && typeof parsed === 'object') {
            record.body = JSON.stringify(scrubJsonValue(parsed))
            return
        }
        if (typeof parsed === 'string') {
            record.body = JSON.stringify(scrubPlainString(parsed))
            return
        }
        // JSON primitives other than string (number, boolean, null): keep canonical serialization
    } catch {
        record.body = scrubPlainString(body)
    }
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
