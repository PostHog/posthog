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
 * - Userinfo (`user:pass@`) is always stripped from the authority.
 * - A scheme without slashes (`mailto:`, `tel:`) is kept; the rest is scrubbed as a path.
 * - With `{ collapseHost: true }`, or when the host matches the context's first-party host
 *   patterns (the team's recording domains), it additionally drops the port and collapses the
 *   host to `example.com` (keeping a leading allow-listed subdomain label).
 */
import { getDomain } from 'tldts'

import { ScrubContext } from './config'
import { ScrubResult } from './text'

export interface UrlScrubOptions {
    collapseHost?: boolean
}

export const URL_ALLOWLIST = ['about:blank', 'about:srcdoc']

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
    if (URL_ALLOWLIST.includes(input)) {
        return { value: input, changed: false }
    }
    const tailIdx = input.search(/[?#]/)
    const base = tailIdx === -1 ? input : input.slice(0, tailIdx)
    const tail = tailIdx === -1 ? '' : input.slice(tailIdx) // starts with ? or #
    let changed = false

    const { scheme, authority, path } = splitUrl(base)
    let out = scheme
    if (authority) {
        const at = authority.lastIndexOf('@')
        if (at !== -1) {
            changed = true
        }
        const hostPort = authority.slice(at + 1)
        if (opts?.collapseHost || isFirstPartyHost(ctx, hostPort)) {
            const collapsed = collapsedHost(ctx, hostPort)
            if (collapsed !== hostPort) {
                changed = true
            }
            out += collapsed
        } else {
            out += hostPort
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

export function firstPartyHostPatterns(recordingDomains: string[] | null | undefined): string[] {
    const patterns: string[] = []
    for (const domain of recordingDomains ?? []) {
        const trimmed = domain.trim()
        if (trimmed === '') {
            continue
        }
        let hostname: string
        try {
            hostname = new URL(trimmed.includes('://') ? trimmed : `https://${trimmed}`).hostname
        } catch {
            continue
        }
        if (hostname.startsWith('*.')) {
            hostname = hostname.slice(2)
        }
        if (hostname === '' || hostname === '*') {
            continue
        }
        patterns.push(getDomain(hostname) ?? hostname)
    }
    return patterns
}

function isFirstPartyHost(ctx: ScrubContext, hostPort: string): boolean {
    const patterns = ctx.firstPartyHosts
    if (!patterns || patterns.length === 0) {
        return false
    }
    const host = hostPort.replace(/:\d+$/, '').toLowerCase()
    return patterns.some((pattern) => host === pattern || host.endsWith(`.${pattern}`))
}

// Drop the port and rewrite the host to example.com. Keep a leading *subdomain* label
// (only when there is one, i.e. ≥3 labels) if it's url-allow-listed: `us.test.com` → `us.example.com`.
function collapsedHost(ctx: ScrubContext, hostPort: string): string {
    const host = hostPort.replace(/:\d+$/, '')
    const labels = host.split('.')
    const first = labels[0] ?? ''
    return labels.length > 2 && first && ctx.allow.urlContains(first) ? `${first}.example.com` : 'example.com'
}

const SCHEME_NO_SLASHES = /^[A-Za-z][A-Za-z0-9+.-]*:/ // RFC 3986 scheme, e.g. `mailto:`, `tel:`

export const URL_SCHEME_ALLOWLIST = new Set([
    // Web platform
    'about',
    'blob',
    'data',
    'file',
    'ftp',
    'geo',
    'javascript',
    'magnet',
    'mailto',
    'sms',
    'tel',
    'urn',
    'ws',
    'wss',
    // Microsoft
    'ms-access',
    'ms-excel',
    'ms-outlook',
    'ms-powerpoint',
    'ms-project',
    'ms-publisher',
    'ms-visio',
    'ms-word',
    'msteams',
    'onenote',
    'sip',
    'sips',
    'skype',
    // Google
    'comgooglemaps',
    'googlechrome',
    'googlegmail',
    'googlemaps',
    // Apple
    'facetime',
    'facetime-audio',
    'itms',
    'itms-apps',
    'maps',
    'music',
    'shortcuts',
    // Chat and social
    'bluesky',
    'callto',
    'discord',
    'fb',
    'fb-messenger',
    'instagram',
    'irc',
    'line',
    'linkedin',
    'matrix',
    'reddit',
    'sgnl',
    'slack',
    'snapchat',
    'telegram',
    'tg',
    'tiktok',
    'twitter',
    'viber',
    'wechat',
    'weixin',
    'whatsapp',
    'xmpp',
    // Media, payments, and tools
    'bitcoin',
    'bittorrent',
    'figma',
    'notion',
    'obsidian',
    'spotify',
    'steam',
    'vscode',
    'zoommtg',
    'zoomus',
])

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
        const m = SCHEME_NO_SLASHES.exec(s)
        if (m && URL_SCHEME_ALLOWLIST.has(m[0].slice(0, -1).toLowerCase())) {
            // No slashes, no authority: everything after the scheme scrubs as a path.
            return { scheme: m[0], authority: '', path: s.slice(m[0].length) }
        }
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
