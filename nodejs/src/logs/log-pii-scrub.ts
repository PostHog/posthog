/**
 * Lossy ingestion scrub: replace matches with PII_REDACTED ({{REDACTED}}). Scrubs `record.body` and each value in
 * `record.attributes` (no JSON parse). Rules: Bearer-shaped tokens, Stripe `sk_*` keys, email addresses.
 * `resource_attributes` and other string fields (e.g. `service_name`, `severity_text`) are not modified here.
 *
 * **Not guaranteed:** secrets only discoverable by JSON object keys inside `body` (no tree walk), values only in
 * JSON number/boolean leaves. PAN-like digit runs are not redacted.
 *
 * One alternated pattern (vs three global passes) for fewer full-string scans. Uses `createTrackedRE2` for
 * linear-time matching; ASCII-explicit classes for stable behavior under node-re2 Unicode mode.
 *
 * Redaction runs as an explicit `exec` loop, not `String.prototype.replace`. RE2 matching is linear, but
 * node-re2's `Symbol.replace` re-walks the subject once per match, so `.replace()` costs the string length
 * times the match count. Scrubbing is synchronous and blocks the ingestion consumer's event loop, so on a
 * multi-megabyte attribute value with tens of thousands of matches that quadratic term is long enough to
 * exceed the consumer's Kafka poll interval and stall the partition. Do not collapse this back into
 * `.replace()`.
 */
import { createTrackedRE2 } from '~/common/utils/tracked-re2'

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
    let pieces: string[] | null = null
    let copiedUpTo = 0

    PII_COMBINED_RE.lastIndex = 0
    let match: RegExpExecArray | null
    while ((match = PII_COMBINED_RE.exec(input)) !== null) {
        const [matched, bearer, stripe, email] = match
        if (matched.length === 0) {
            PII_COMBINED_RE.lastIndex += 1
            continue
        }

        let replacement: string
        if (bearer !== undefined) {
            replacement = `Bearer ${PII_REDACTED}`
        } else if (stripe !== undefined) {
            replacement = PII_REDACTED
        } else if (email !== undefined) {
            replacement = PII_REDACTED
        } else {
            continue
        }
        piiReplacements += 1

        pieces ??= []
        pieces.push(input.slice(copiedUpTo, match.index), replacement)
        copiedUpTo = match.index + matched.length
    }

    if (pieces === null) {
        return { output: input, piiReplacements }
    }
    pieces.push(input.slice(copiedUpTo))
    return { output: pieces.join(''), piiReplacements }
}

/** Apply regex-based redaction to a single string (e.g. log body). */
export function scrubPlainString(input: string): string {
    return scrubPlainStringWithStats(input).output
}

/**
 * Mutate record in place: `body` and each `attributes` value.
 * `piiReplacements` is the sum of all successful redactions (body + every attribute value), not split by field.
 */
export function scrubLogRecord(record: LogRecord): PiiScrubStats {
    let piiReplacements = 0

    if (record.body != null) {
        const { output, piiReplacements: n } = scrubPlainStringWithStats(record.body)
        record.body = output
        piiReplacements += n
    }

    if (record.attributes != null) {
        for (const [key, val] of Object.entries(record.attributes)) {
            const { output, piiReplacements: n } = scrubPlainStringWithStats(val)
            record.attributes[key] = output
            piiReplacements += n
        }
    }

    return piiReplacements === 0 ? EMPTY_PII : { piiReplacements }
}
