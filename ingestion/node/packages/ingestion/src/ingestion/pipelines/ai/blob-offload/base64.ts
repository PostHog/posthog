/**
 * Canonical base64 grammar for blob offload — the only module that validates or
 * decodes base64. Guarantee: when decodeCanonicalBase64 returns bytes,
 * bytes.toString('base64') === candidate, so replacing the string with a pointer
 * is exactly invertible. Node's lenient decoder (skips invalid chars, accepts
 * base64url, stops at interior '=') must never be reached with unvalidated input;
 * the full-string scan below is load-bearing and must not be sampled away.
 */

const CANONICAL_BASE64 = /^[A-Za-z0-9+/]+={0,2}$/
const BASE64_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
const WINDOW_CHARS = 64

// Encoders emit zero discarded bits in the final quantum; nonzero bits would
// decode and re-encode to a different string, breaking invertibility.
function discardedBitsAreZero(candidate: string): boolean {
    if (candidate.endsWith('==')) {
        const index = BASE64_ALPHABET.indexOf(candidate[candidate.length - 3])
        return index >= 0 && (index & 0b1111) === 0
    }
    if (candidate.endsWith('=')) {
        const index = BASE64_ALPHABET.indexOf(candidate[candidate.length - 2])
        return index >= 0 && (index & 0b11) === 0
    }
    return true
}

// Reject-path pre-filter: long almost-base64 strings (wrapped base64, prose,
// hex with separators) die on an O(1) window instead of a full scan.
function windowsLookCanonical(candidate: string): boolean {
    if (candidate.length <= WINDOW_CHARS * 2) {
        return true
    }
    return (
        CANONICAL_BASE64.test(candidate.slice(0, WINDOW_CHARS)) && CANONICAL_BASE64.test(candidate.slice(-WINDOW_CHARS))
    )
}

export function isCanonicalBase64(value: unknown): value is string {
    return (
        typeof value === 'string' &&
        value.length > 0 &&
        value.length % 4 === 0 &&
        CANONICAL_BASE64.test(value) &&
        discardedBitsAreZero(value)
    )
}

export function decodeCanonicalBase64(candidate: string): Buffer | null {
    if (!windowsLookCanonical(candidate) || !isCanonicalBase64(candidate)) {
        return null
    }
    return Buffer.from(candidate, 'base64')
}
