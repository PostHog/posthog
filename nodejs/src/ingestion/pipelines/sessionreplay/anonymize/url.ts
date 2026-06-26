/**
 * URL scrub.
 *
 * - Path: replace each non-safe, non-allow-listed segment with `[redacted]`.
 * - Query/fragment: keep only *simple* parts — a query param survives iff its key is url-allow-listed
 *   and both key and value are 100% alphanumeric; a fragment survives iff it is allow-listed and
 *   alphanumeric. Anything else (tokens, encoded values, emails, JSON, …) is dropped.
 */
import { ScrubContext } from './config'
import { ScrubResult } from './text'

export interface UrlScrubOptions {
    scrubAuthority?: boolean
}

// "Simple" = 100% alphanumeric (empty allowed). Disallows tokens, encodings, punctuation, etc.
const SIMPLE = /^[A-Za-z0-9]*$/

export function scrubUrl(ctx: ScrubContext, input: string, opts?: UrlScrubOptions): ScrubResult {
    const tailIdx = input.search(/[?#]/)
    const base = tailIdx === -1 ? input : input.slice(0, tailIdx)
    const tail = tailIdx === -1 ? '' : input.slice(tailIdx) // starts with ? or #
    let changed = false

    const { scheme, authority, path } = splitUrl(base)
    let out = scheme
    if (authority) {
        if (opts?.scrubAuthority) {
            const scrubbed = scrubHost(ctx, authority)
            if (scrubbed !== authority) {
                changed = true
            }
            out += scrubbed
        } else {
            out += authority
        }
    }

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

    const tailOut = scrubTail(ctx, tail)
    if (tailOut !== tail) {
        changed = true
    }
    out += tailOut

    return { value: out, changed }
}

// Keep only allow-listed, alphanumeric query params and an allow-listed alphanumeric fragment.
function scrubTail(ctx: ScrubContext, tail: string): string {
    if (tail === '') {
        return ''
    }
    let query = ''
    let frag = ''
    if (tail[0] === '?') {
        const h = tail.indexOf('#')
        query = h === -1 ? tail.slice(1) : tail.slice(1, h)
        frag = h === -1 ? '' : tail.slice(h + 1)
    } else {
        frag = tail.slice(1) // tail starts with '#'
    }

    let out = ''
    if (tail[0] === '?') {
        const kept: string[] = []
        for (const pair of query.split('&')) {
            if (pair === '') {
                continue
            }
            const eq = pair.indexOf('=')
            const key = eq === -1 ? pair : pair.slice(0, eq)
            const value = eq === -1 ? '' : pair.slice(eq + 1)
            if (key.length > 0 && SIMPLE.test(key) && SIMPLE.test(value) && ctx.allow.urlContains(key)) {
                kept.push(eq === -1 ? key : `${key}=${value}`)
            }
        }
        if (kept.length > 0) {
            out += '?' + kept.join('&')
        }
    }
    if (frag.length > 0 && SIMPLE.test(frag) && ctx.allow.urlContains(frag)) {
        out += '#' + frag
    }
    return out
}

// Strip userinfo + port and rewrite the host to example.com. Keep a leading *subdomain* label
// (only when there is one, i.e. ≥3 labels) if it's url-allow-listed: `us.test.com` → `us.example.com`.
function scrubHost(ctx: ScrubContext, authority: string): string {
    const at = authority.lastIndexOf('@')
    let host = at !== -1 ? authority.slice(at + 1) : authority
    host = host.replace(/:\d+$/, '') // drop :port
    const labels = host.split('.')
    const first = labels[0] ?? ''
    return labels.length > 2 && first && ctx.allow.urlContains(first) ? `${first}.example.com` : 'example.com'
}

// Split into scheme prefix (incl. `://` or `//`), authority (`[userinfo@]host[:port]`), and path.
function splitUrl(s: string): { scheme: string; authority: string; path: string } {
    let scheme = ''
    let rest = s
    const schemeEnd = s.indexOf('://')
    if (schemeEnd !== -1) {
        scheme = s.slice(0, schemeEnd + 3)
        rest = s.slice(schemeEnd + 3)
    } else if (s.startsWith('//')) {
        scheme = '//'
        rest = s.slice(2)
    } else {
        return { scheme: '', authority: '', path: s } // relative URL: all path
    }
    const pathOff = rest.indexOf('/')
    if (pathOff === -1) {
        return { scheme, authority: rest, path: '' }
    }
    return { scheme, authority: rest.slice(0, pathOff), path: rest.slice(pathOff) }
}

function isSafeSegment(seg: string): boolean {
    return seg === '' || seg === '.' || seg === '..'
}
