import { Properties } from '~/plugin-scaffold'

// Hostnames that unambiguously identify a local/dev environment.
const LOCAL_HOSTNAMES = new Set(['localhost', '0.0.0.0', '::1', '::'])

// Reserved/local-only DNS suffixes (RFC 6761/8375 and common dev conventions).
const LOCAL_SUFFIXES = [
    '.localhost',
    '.local',
    '.test',
    '.internal',
    '.invalid',
    '.example',
    '.localdomain',
    '.home.arpa',
]

/**
 * Decides whether an event clearly originates from a real, public (production) environment
 * rather than a developer's local machine.
 *
 * The only trustworthy origin signal at ingestion time is the browser SDK's `$host`
 * (from `window.location.host`), falling back to the host parsed from `$current_url`.
 * We deliberately require a *positive* public-host signal: anything local, private, or
 * absent returns `false` (no production event fired).
 *
 * In particular we do NOT fire when there is no host at all. Server-side SDKs
 * (posthog-python/node/go), mobile SDKs and `file://` pages don't set `$host`, and a
 * developer running their backend locally reaches PostHog from a *public* IP — so a
 * missing host can't be distinguished from production. Guessing there would create
 * false positives, so we stay silent.
 */
export function isProductionEventOrigin(properties: Properties): boolean {
    const host = extractHost(properties)
    if (!host) {
        return false
    }
    const hostname = normalizeHostname(host)
    if (!hostname) {
        return false
    }
    return !isLocalHostname(hostname)
}

function extractHost(properties: Properties): string | null {
    const rawHost = properties.$host
    if (typeof rawHost === 'string' && rawHost.length > 0) {
        return rawHost
    }
    const currentUrl = properties.$current_url
    if (typeof currentUrl === 'string' && currentUrl.length > 0) {
        try {
            return new URL(currentUrl).host
        } catch {
            return null
        }
    }
    return null
}

// Lowercase and strip any port, handling bracketed IPv6 (`[::1]:3000`) and bare IPv6.
function normalizeHostname(host: string): string {
    const h = host.trim().toLowerCase()
    if (h.startsWith('[')) {
        const end = h.indexOf(']')
        return end !== -1 ? h.slice(1, end) : h.slice(1)
    }
    const colonCount = (h.match(/:/g) || []).length
    // A bare IPv6 address has multiple colons and no port to strip.
    if (colonCount >= 2) {
        return h
    }
    if (colonCount === 1) {
        return h.slice(0, h.indexOf(':'))
    }
    return h
}

function isLocalHostname(hostname: string): boolean {
    if (hostname.length === 0) {
        return true
    }
    if (LOCAL_HOSTNAMES.has(hostname)) {
        return true
    }
    if (LOCAL_SUFFIXES.some((suffix) => hostname.endsWith(suffix))) {
        return true
    }
    if (isIpv4(hostname)) {
        return isPrivateIpv4(hostname)
    }
    if (hostname.includes(':')) {
        return isPrivateIpv6(hostname)
    }
    // A bare single-label hostname (no dot, not an IP) is a machine name like
    // "my-laptop", never a real public domain.
    return !hostname.includes('.')
}

function isIpv4(hostname: string): boolean {
    const parts = hostname.split('.')
    return parts.length === 4 && parts.every((p) => /^\d{1,3}$/.test(p) && Number(p) <= 255)
}

function isPrivateIpv4(hostname: string): boolean {
    const [a, b] = hostname.split('.').map(Number)
    if (a === 0 || a === 10 || a === 127) {
        return true
    }
    if (a === 192 && b === 168) {
        return true
    }
    if (a === 172 && b >= 16 && b <= 31) {
        return true
    }
    // Link-local (APIPA).
    return a === 169 && b === 254
}

function isPrivateIpv6(hostname: string): boolean {
    if (hostname === '::1' || hostname === '::') {
        return true
    }
    // Unique-local fc00::/7 (fc.. / fd..) and link-local fe80::/10 (fe8x-febx).
    return /^f[cd]/.test(hostname) || /^fe[89ab]/.test(hostname)
}
