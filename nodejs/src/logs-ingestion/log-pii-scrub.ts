/**
 * Lossy ingestion scrub: replace matches with PII_REDACTED ({{REDACTED}}).
 *
 * Bodies and plain-text metadata: one pass of regex rules (Bearer-shaped tail, Stripe sk_*,
 * email, Luhn-valid card-like digit runs) via RE2 — no JSON parse or structured walk of the body.
 * Under-scrub: values only protected today by JSON *key names* inside the body may remain unless
 * they match a pattern (attribute maps still use sensitive-key redaction).
 *
 * Attribute maps: sensitive key → full redact; else unwrap OTLP JSON-string cells
 * (tryDecodeJsonStringDocument — a single string literal, not a full document parse), pattern-scrub,
 * then encodeAttributeCell for ClickHouse / Rust OTLP parity.
 *
 * The four main match rules use RE2 (via createTrackedRE2) for linear-time matching and consistency
 * with other nodejs regex paths; patterns use ASCII-explicit classes under node-re2’s Unicode mode.
 */
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

/**
 * If `raw` is a JSON document consisting of a single string literal, return its decoded Unicode value; otherwise null.
 * Avoids JSON.parse so scrub stays off the hot parse metrics path; only handles the OTLP/CH string-cell shape.
 */
function tryDecodeJsonStringDocument(raw: string): string | null {
    const s = raw.trim()
    if (s.length < 2 || s.charCodeAt(0) !== 0x22 || s.charCodeAt(s.length - 1) !== 0x22) {
        return null
    }
    let i = 1
    const end = s.length - 1
    let out = ''
    while (i < end) {
        const c = s.charCodeAt(i)
        if (c !== 0x5c) {
            if (c < 0x20) {
                return null
            }
            out += s[i]
            i++
            continue
        }
        i++
        if (i >= end) {
            return null
        }
        const esc = s[i]
        switch (esc) {
            case '"':
                out += '"'
                i++
                break
            case '\\':
                out += '\\'
                i++
                break
            case '/':
                out += '/'
                i++
                break
            case 'b':
                out += '\b'
                i++
                break
            case 'f':
                out += '\f'
                i++
                break
            case 'n':
                out += '\n'
                i++
                break
            case 'r':
                out += '\r'
                i++
                break
            case 't':
                out += '\t'
                i++
                break
            case 'u': {
                if (i + 4 >= end) {
                    return null
                }
                const hex = s.slice(i + 1, i + 5)
                if (!/^[0-9a-fA-F]{4}$/.test(hex)) {
                    return null
                }
                let cp = parseInt(hex, 16)
                i += 5
                if (cp >= 0xd800 && cp <= 0xdbff && i + 5 < end && s[i] === '\\' && s[i + 1] === 'u') {
                    const hexLow = s.slice(i + 2, i + 6)
                    if (/^[0-9a-fA-F]{4}$/.test(hexLow)) {
                        const low = parseInt(hexLow, 16)
                        if (low >= 0xdc00 && low <= 0xdfff) {
                            cp = 0x10000 + ((cp - 0xd800) << 10) + (low - 0xdc00)
                            out += String.fromCodePoint(cp)
                            i += 6
                            break
                        }
                    }
                }
                out += String.fromCharCode(cp)
                break
            }
            default:
                return null
        }
    }
    return i === end ? out : null
}

/** Rust OTLP path stores string attrs as serde_json string values; unwrap one JSON string layer if present. */
export function unwrapAttributeCell(value: string): string {
    return tryDecodeJsonStringDocument(value) ?? value
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
