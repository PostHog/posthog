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

function canonicalizeHost(host: string): string {
    // domainToASCII lowercases and applies the IDNA mapping the resolver queries, so a fullwidth or
    // uppercase form of a listed name reaches the same entry. It returns an empty string for a name
    // the codec rejects, and the lowercased input is then the closest form available.
    const canonical = domainToASCII(host) || host.toLowerCase()
    // An absolute FQDN carries the DNS root dot, which the list does not.
    return canonical.replace(/\.+$/, '')
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
    const canonical = canonicalizeHost(host)
    return OOB_DOMAINS.find((domain) => canonical === domain || canonical.endsWith(`.${domain}`)) ?? null
}

/**
 * Record a lookup of an out-of-band interaction domain, without refusing it.
 *
 * These names resolve to ordinary public IPs, so every IP check passes them, while the lookup alone
 * confirms the path to whoever runs the collaborator. Detection only: this never throws and never
 * changes what the caller does. Call it before the resolve, so the later blocking phase is a small
 * change.
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
        if (domain !== null) {
            logger.info('security.oob_domain_seen', { ...context, host, domain, guard })
        }
    } catch (error) {
        logger.warn('security.oob_domain_check_failed', { host, guard, error })
    }
}
