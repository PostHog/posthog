import { domainToASCII } from 'node:url'

import { isCloud } from './env-utils'
import { logger } from './logger'

/**
 * Mirror of posthog/security/crosslang/oob_domains.json. Edit that file first, then this list. The
 * parity test in oob-domains.test.ts fails when they differ.
 */
export const OOB_DOMAINS: readonly string[] = [
    '1u.ms',
    'burpcollaborator.net',
    'ceye.io',
    'dnslog.cn',
    'interact.sh',
    'oast.fun',
    'oast.live',
    'oast.me',
    'oast.online',
    'oast.pro',
    'oast.site',
    'oastify.com',
    'rbndr.us',
]

/** The guard that saw the host. One value per call site, so a log line names the path. */
export type OobGuard = 'node_request' | 'node_email_validation'

/**
 * One line per host, team and guard in this window. A CDP destination retries, and undici reuses a
 * keep-alive socket without a fresh lookup, so an undeduped count tracks request volume rather than
 * probing. The window stays short enough that a sustained campaign still reads as repeated activity.
 */
const DEDUPE_WINDOW_MS = 15 * 60 * 1000
const DEDUPE_MAX_ENTRIES = 10_000

const lastLoggedAt = new Map<string, number>()

/** Whether this key was last logged outside the window. Bounded by size, so it needs no timer. */
function firstSightInWindow(key: string, now: number): boolean {
    const seenAt = lastLoggedAt.get(key)
    if (seenAt !== undefined && now - seenAt < DEDUPE_WINDOW_MS) {
        return false
    }
    // Deleting before setting moves the key to the end, so iteration order stays recency order and
    // the front of the map is always the oldest entry.
    lastLoggedAt.delete(key)
    lastLoggedAt.set(key, now)
    while (lastLoggedAt.size > DEDUPE_MAX_ENTRIES) {
        const oldest = lastLoggedAt.keys().next().value
        if (oldest === undefined) {
            break
        }
        lastLoggedAt.delete(oldest)
    }
    return true
}

const MAX_DNS_NAME_LENGTH = 253

// A host of letters, digits, dots, hyphens and underscores needs no IDNA pass, because
// domainToASCII would only lowercase it.
const PLAIN_HOST_RE = /^[A-Za-z0-9._-]+$/

function canonicalizeHost(host: string): string | null {
    // domainToASCII applies the IDNA mapping the resolver queries, so a fullwidth or uppercase form
    // of a listed name reaches the same entry. It returns an empty string for a name the codec
    // rejects. Such a string is not a host, and matching it would put a form the parser refused,
    // such as one carrying a fullwidth @ or a colon, into a log line.
    const canonical = PLAIN_HOST_RE.test(host) ? host.toLowerCase() : domainToASCII(host)
    if (!canonical) {
        return null
    }
    // An absolute FQDN carries the DNS root dot, which the list does not. A loop strips it, because
    // /\.+$/ backtracks in quadratic time on a long run of dots inside the host, and an email
    // recipient puts no limit on that run.
    let end = canonical.length
    while (end > 0 && canonical[end - 1] === '.') {
        end--
    }
    return canonical.slice(0, end)
}

/**
 * The listed out-of-band interaction domain this host belongs to, or null.
 *
 * The caller passes a parsed hostname. A raw URL or a credential never matches, because a match
 * puts the string in a log line.
 */
export function matchedOobDomain(host: string | null | undefined): string | null {
    if (!host || host.includes('@') || host.includes('/')) {
        return null
    }
    if ((host.endsWith('.') ? host.length - 1 : host.length) > MAX_DNS_NAME_LENGTH) {
        // A longer name never resolves, and a match keeps the host in the dedupe map and the log line.
        return null
    }
    const canonical = canonicalizeHost(host)
    if (canonical === null) {
        return null
    }
    return OOB_DOMAINS.find((domain) => canonical === domain || canonical.endsWith(`.${domain}`)) ?? null
}

/**
 * Record a lookup of an out-of-band interaction domain, without refusing it.
 *
 * These names resolve to ordinary public IPs, so every IP check passes them, while the lookup alone
 * confirms the path to whoever runs the collaborator. Detection only: this never throws and never
 * changes what the caller does. Call it before the resolve, so the later blocking phase is a small
 * change.
 *
 * `context.teamId` is logged as `team_id`, which is the field the Python guards bind.
 */
export function noteOobDomain(
    host: string | null | undefined,
    guard: OobGuard,
    context: Record<string, unknown> = {}
): void {
    if (!isCloud()) {
        return
    }
    try {
        const domain = matchedOobDomain(host)
        if (domain === null) {
            return
        }
        const { teamId, ...rest } = context
        if (!firstSightInWindow(`${guard}\u0000${teamId ?? 'none'}\u0000${host}`, Date.now())) {
            return
        }
        logger.info('security.oob_domain_seen', { ...rest, team_id: teamId ?? null, host, domain, guard })
    } catch (error) {
        logger.warn('security.oob_domain_check_failed', { host, guard, error })
    }
}
