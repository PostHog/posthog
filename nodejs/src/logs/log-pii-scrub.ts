/**
 * Lossy ingestion scrub: replace matches with PII_REDACTED ({{REDACTED}}). Scrubs `record.body` and each value in
 * `record.attributes` (no JSON parse). Rules: Bearer-shaped tokens, credential shapes that carry their own issuer
 * prefix (Stripe, GitHub, Slack, AWS access key ids, JWTs), and email addresses.
 * `resource_attributes` and other string fields (e.g. `service_name`, `severity_text`) are not modified here.
 *
 * Every rule matches on the shape of the secret itself. That is what lets the scrub run on any string without a
 * parse, and it is why the rule set grows by issuer prefix rather than by secret-holding key name.
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

export type PiiRuleName = 'bearer' | 'stripe' | 'github' | 'slack' | 'aws_access_key_id' | 'jwt' | 'email'

export type PiiRule = {
    name: PiiRuleName
    pattern: string
    replacement: string
}

/**
 * One capture group per rule, in this order, because the redaction loop reads the fired rule off the
 * group index. A rule may not add a group of its own, and `bearer` and `email` keep their original
 * positions so the legacy three-pass order still decides every tie they were deciding before.
 *
 * Rules are ordered issuer-prefix first, `email` last. Only ties matter: RE2 takes the leftmost match
 * and prefers the earlier alternative when two start at the same offset, so `Bearer eyJ...` redacts as
 * a bearer token rather than splitting into a prefix and a JWT.
 */
export const PII_RULES: readonly PiiRule[] = [
    { name: 'bearer', pattern: '(?i:Bearer\\s+[-A-Za-z0-9._~+/]+=*)', replacement: `Bearer ${PII_REDACTED}` },
    { name: 'stripe', pattern: '\\bsk_(?:live|test)_[a-zA-Z0-9]{20,}\\b', replacement: PII_REDACTED },
    // ghp_ personal, gho_ oauth, ghu_ user-to-server, ghs_ server, ghr_ refresh. GitHub issues all of
    // them as 36 base62 chars. The floor of 20 accepts a shorter reissue without a code change.
    { name: 'github', pattern: '\\bgh[pousr]_[A-Za-z0-9]{20,}\\b', replacement: PII_REDACTED },
    { name: 'slack', pattern: '\\bxox[abeprs]-[A-Za-z0-9-]{10,}\\b', replacement: PII_REDACTED },
    { name: 'aws_access_key_id', pattern: '\\b(?:AKIA|ASIA)[0-9A-Z]{16}\\b', replacement: PII_REDACTED },
    // `eyJ` is base64url for `{"`, so this reaches any JWT whose header is a JSON object, whatever
    // signed it. The signature part is unbounded rather than required: `alg: none` leaves it empty.
    {
        name: 'jwt',
        pattern: '\\beyJ[A-Za-z0-9_-]{10,}\\.[A-Za-z0-9_-]{4,}\\.[A-Za-z0-9_-]*',
        replacement: PII_REDACTED,
    },
    { name: 'email', pattern: '\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}\\b', replacement: PII_REDACTED },
]

const PII_COMBINED_RE = createTrackedRE2(
    PII_RULES.map((rule) => `(${rule.pattern})`).join('|'),
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
        const matched = match[0]
        if (matched.length === 0) {
            PII_COMBINED_RE.lastIndex += 1
            continue
        }

        // Indexed loop, not `findIndex`: a callback here allocates a closure per match, which is
        // the cost this loop exists to avoid.
        let replacement: string | null = null
        for (let i = 0; i < PII_RULES.length; i++) {
            if (match[i + 1] !== undefined) {
                replacement = PII_RULES[i].replacement
                break
            }
        }
        if (replacement === null) {
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
