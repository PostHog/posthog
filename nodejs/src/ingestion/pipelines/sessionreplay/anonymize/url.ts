/**
 * URL scrub.
 *
 * - Numbers (a bare run of digits) are masked to `$` per digit (length-preserving; `$` rather than `#`
 *   so it doesn't clash with the fragment separator).
 * - Path: keep allow-listed segments; a number → `$$`; anything else → `[redacted]`.
 * - Query: a param survives only if its key or value is an allow-listed alphanumeric token. A number
 *   counts as denied for survival, so `id=42` is dropped while `page=2` → `page=$`. When a param
 *   survives, each side renders independently: allow-listed → kept, number → `$$`, denied → `[key]`/`[value]`.
 * - Fragment: kept only if it is an allow-listed alphanumeric token; numbers and everything else dropped.
 * - With `{ scrubAuthority: true }` it strips userinfo/port and
 *   collapses the host to `example.com` (keeping a leading allow-listed subdomain label).
 */
import { ScrubContext } from './config'
import { ScrubResult } from './text'

export interface UrlScrubOptions {
    scrubAuthority?: boolean
}

const SIMPLE = /^[A-Za-z0-9]*$/ // 100% alphanumeric (empty allowed)
const NUMERIC = /^[0-9]+$/ // a bare number

const maskNumber = (n: string): string => '$'.repeat(n.length) // `$`, not `#` (the fragment separator)

// An allow-listed, alphanumeric, non-number token — the only kind that keeps a query param/fragment
// alive.
function isAllowed(ctx: ScrubContext, t: string): boolean {
    return t.length > 0 && SIMPLE.test(t) && !NUMERIC.test(t) && ctx.allow.urlContains(t)
}

// Rendered form of a surviving token: a number → `$$`, an allow-listed token → itself, else null.
function renderToken(ctx: ScrubContext, t: string): string | null {
    return NUMERIC.test(t) ? maskNumber(t) : isAllowed(ctx, t) ? t : null
}

export function scrubUrl(ctx: ScrubContext, input: string, opts?: UrlScrubOptions): ScrubResult {
    // rrweb's standard blank-iframe placeholder: entropy-free, so redacting it only costs replay fidelity.
    if (input === 'about:blank') {
        return { value: input, changed: false }
    }
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
        if (NUMERIC.test(raw)) {
            out += maskNumber(raw) // a bare number → $$
            changed = true
        } else if (isSafeSegment(raw) || ctx.allow.urlContains(raw)) {
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
            if (eq === -1) {
                if (isAllowed(ctx, pair)) {
                    kept.push(pair)
                }
                continue
            }
            const key = pair.slice(0, eq)
            const value = pair.slice(eq + 1)
            if (!isAllowed(ctx, key) && !(value !== '' && isAllowed(ctx, value))) {
                continue
            }
            const kr = renderToken(ctx, key) ?? '[key]'
            const vr = value === '' ? '' : (renderToken(ctx, value) ?? '[value]')
            kept.push(`${kr}=${vr}`)
        }
        if (kept.length > 0) {
            out += '?' + kept.join('&')
        }
    }
    if (frag.length > 0 && isAllowed(ctx, frag)) {
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
