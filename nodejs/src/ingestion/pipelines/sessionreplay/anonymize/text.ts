/** Length-preserving text scrub: numeric tokens → `#`, allow-listed words kept, everything else → `*`. */
import { AllowLists } from './allow-lists'
import { NUMBER_CHAR, REDACT_CHAR, ScrubContext } from './config'

export interface ScrubResult {
    value: string
    changed: boolean
}

// A "word" is a maximal run of word chars: Unicode letters/numbers, `_`, `'`, `’`.
const WORD_RE = /[\p{L}\p{N}_'’]+/gu

export function scrubText(ctx: ScrubContext, input: string): ScrubResult {
    const forceRedactAll = exceedsWordLimit(input, ctx.maxWordsLen)
    let changed = false
    let out = ''
    let lastIndex = 0

    WORD_RE.lastIndex = 0
    let match: RegExpExecArray | null
    while ((match = WORD_RE.exec(input)) !== null) {
        const word = match[0]
        const start = match.index
        if (start > lastIndex) {
            out += input.slice(lastIndex, start)
        }
        const emitted = emitWord(word, ctx.allow, forceRedactAll)
        out += emitted.value
        changed = changed || emitted.changed
        lastIndex = WORD_RE.lastIndex
    }
    if (lastIndex < input.length) {
        out += input.slice(lastIndex)
    }

    return { value: out, changed }
}

// True if `input` has more than `max` words. Stops scanning once the limit is
// exceeded rather than counting every word in long free-text blobs.
function exceedsWordLimit(input: string, max: number): boolean {
    WORD_RE.lastIndex = 0
    let n = 0
    while (WORD_RE.exec(input) !== null) {
        if (++n > max) {
            return true
        }
    }
    return false
}

function emitWord(word: string, allow: AllowLists, forceRedactAll: boolean): ScrubResult {
    if (isNumericToken(word)) {
        return { value: redact(word, NUMBER_CHAR), changed: true }
    }
    if (forceRedactAll) {
        return { value: redact(word, REDACT_CHAR), changed: true }
    }
    if (wordIsAllowed(allow, word)) {
        return { value: word, changed: false }
    }
    return { value: redact(word, REDACT_CHAR), changed: true }
}

/** Length-preserving redaction: one mark per source code point (not UTF-16 unit). */
function redact(word: string, mark: string): string {
    return mark.repeat(codePointLength(word))
}

function codePointLength(s: string): number {
    let n = 0
    for (let i = 0; i < s.length; i++) {
        n++
        const c = s.charCodeAt(i)
        if (c >= 0xd800 && c <= 0xdbff && i + 1 < s.length) {
            i++ // skip the low surrogate
        }
    }
    return n
}

function wordIsAllowed(allow: AllowLists, word: string): boolean {
    if (allow.textContains(word)) {
        return true
    }
    if (word.includes('’')) {
        const normalized = word.replace(/’/g, "'")
        if (allow.textContains(normalized)) {
            return true
        }
        const base = stripPossessive(normalized)
        if (base !== null && allow.textContains(base)) {
            return true
        }
    }
    const base = stripPossessive(word)
    if (base !== null && allow.textContains(base)) {
        return true
    }
    return false
}

function stripPossessive(word: string): string | null {
    for (const suffix of ["'s", '’s', "'", '’']) {
        if (word.endsWith(suffix)) {
            const base = word.slice(0, word.length - suffix.length)
            if (base.length > 0) {
                return base
            }
        }
    }
    return null
}

function isNumericToken(word: string): boolean {
    let sawDigit = false
    for (const c of word) {
        if (c >= '0' && c <= '9') {
            sawDigit = true
        } else if (c !== '.' && c !== ',' && c !== '-' && c !== '+') {
            return false
        }
    }
    return sawDigit
}
