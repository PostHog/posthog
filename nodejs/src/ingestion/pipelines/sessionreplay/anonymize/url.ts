/**
 * URL scrub.
 *
 * Keeps scheme + authority verbatim, drops everything from the first `?`/`#`,
 * and replaces each non-safe, non-allow-listed path segment with `[redacted]`.
 */
import { ScrubContext } from './config'
import { ScrubResult } from './text'

export function scrubUrl(ctx: ScrubContext, input: string): ScrubResult {
    const split = splitAtAny(input, ['?', '#'])
    const [pathAndAuthority, dropped] = split ?? [input, '']
    let changed = dropped.length > 0

    const [prefix, path] = splitAuthority(pathAndAuthority)
    let out = prefix

    let first = true
    for (const raw of path.split('/')) {
        if (first) {
            first = false
        } else {
            out += '/'
        }
        if (raw.length === 0) {
            continue
        }
        if (isSafeSegment(raw) || ctx.allow.urlContains(raw)) {
            out += raw
        } else {
            out += '[redacted]'
            changed = true
        }
    }

    return { value: out, changed }
}

function splitAuthority(s: string): [string, string] {
    const schemeEnd = s.indexOf('://')
    if (schemeEnd !== -1) {
        const after = s.slice(schemeEnd + 3)
        const pathOff = after.indexOf('/')
        if (pathOff !== -1) {
            const splitIdx = schemeEnd + 3 + pathOff
            return [s.slice(0, splitIdx), s.slice(splitIdx)]
        }
        return [s, '']
    }
    if (s.startsWith('//')) {
        const rest = s.slice(2)
        const pathOff = rest.indexOf('/')
        if (pathOff !== -1) {
            const splitIdx = 2 + pathOff
            return [s.slice(0, splitIdx), s.slice(splitIdx)]
        }
        return [s, '']
    }
    return ['', s]
}

function splitAtAny(s: string, delims: string[]): [string, string] | null {
    for (let i = 0; i < s.length; i++) {
        if (delims.includes(s[i])) {
            return [s.slice(0, i), s.slice(i)]
        }
    }
    return null
}

function isSafeSegment(seg: string): boolean {
    return seg === '' || seg === '.' || seg === '..'
}
