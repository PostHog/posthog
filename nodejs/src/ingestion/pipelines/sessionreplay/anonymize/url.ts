/**
 * URL scrub.
 *
 * Drops everything from the first `?`/`#` and replaces each non-safe, non-allow-listed path
 * segment with `[redacted]`.
 */
import { ScrubContext } from './config'
import { ScrubResult } from './text'

export interface UrlScrubOptions {
    scrubAuthority?: boolean
}

export function scrubUrl(ctx: ScrubContext, input: string, opts?: UrlScrubOptions): ScrubResult {
    const split = splitAtAny(input, ['?', '#'])
    const [pathAndAuthority, dropped] = split ?? [input, '']
    let changed = dropped.length > 0

    const { scheme, authority, path } = splitUrl(pathAndAuthority)
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

    return { value: out, changed }
}

// Strip userinfo + port and rewrite the host to example.com. Keep a leading *subdomain* label
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
