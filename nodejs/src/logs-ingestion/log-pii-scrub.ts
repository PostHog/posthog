/**
 * Lossy ingestion scrub: replace matches with PII_REDACTED ({{REDACTED}}). Only `record.body` is scrubbed — one
 * RE2 pass over the raw UTF-8 string (no JSON parse). Rules: Bearer-shaped tokens, Stripe `sk_*` keys, email
 * addresses. OTLP `attributes` / `resource_attributes` and other string fields are not modified here.
 *
 * **Not guaranteed:** secrets only discoverable by JSON object keys inside `body` (no tree walk), values only in
 * JSON number/boolean leaves. PAN-like digit runs are not redacted.
 *
 * One alternated pattern with a replace callback (vs three global passes) for fewer full-string scans. Uses
 * `createTrackedRE2` for linear-time matching; ASCII-explicit classes for stable behavior under node-re2 Unicode mode.
 */
import { createTrackedRE2 } from '../utils/tracked-re2'
import type { LogRecord } from './log-record-avro'

export const PII_REDACTED = '{{REDACTED}}'

export type PiiScrubStats = {
    readonly piiReplacements: number
}

export const EMPTY_PII: Readonly<PiiScrubStats> = Object.freeze({ piiReplacements: 0 })

/** Match Rust serde_json::Value::String(s).to_string() / CH kafka_logs_avro_mv JSONExtractString expectations. */
export function encodeAttributeCell(semantic: string): string {
    return JSON.stringify(semantic)
}

/** Bearer (group 1), Stripe sk_* (group 2), email (group 3). Order matches legacy three-pass behavior. */
const PII_COMBINED_RE = createTrackedRE2(
    '((?i:Bearer\\s+[-A-Za-z0-9._~+/]+=*))' +
        '|(\\bsk_(?:live|test)_[a-zA-Z0-9]{20,}\\b)' +
        '|(\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}\\b)',
    'g',
    'log-pii-scrub:combined'
)

/** One regex pass; `piiReplacements` counts only successful redactions (a matched capture group). */
export function scrubPlainStringWithStats(input: string): { output: string; piiReplacements: number } {
    let piiReplacements = 0
    const output = input.replace(
        PII_COMBINED_RE,
        (match: string, bearer: string | undefined, stripe: string | undefined, email: string | undefined) => {
            if (bearer !== undefined) {
                piiReplacements += 1
                return `Bearer ${PII_REDACTED}`
            }
            if (stripe !== undefined) {
                piiReplacements += 1
                return PII_REDACTED
            }
            if (email !== undefined) {
                piiReplacements += 1
                return PII_REDACTED
            }
            return match
        }
    )
    return { output, piiReplacements }
}

/** Apply regex-based redaction to a single string (e.g. log body). */
export function scrubPlainString(input: string): string {
    return scrubPlainStringWithStats(input).output
}

/** Mutate record in place: `body` only. Returns PII replacement count for that record. */
export function scrubLogRecord(record: LogRecord): PiiScrubStats {
    if (record.body == null) {
        return EMPTY_PII
    }
    const { output, piiReplacements } = scrubPlainStringWithStats(record.body)
    record.body = output
    return { piiReplacements }
}
