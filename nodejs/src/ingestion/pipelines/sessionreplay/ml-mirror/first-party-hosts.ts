import { parse as parseHostname } from 'tldts'

/**
 * Cap on the emitted patterns, applied after registrable-domain reduction and dedup so it counts
 * root domains, not subdomain entries. Bounds the per-URL pattern scan in the anonymizer; safe to
 * truncate because the recorded page's own domain still collapses via its `$snapshot_host` stamp,
 * so overflow domains only fall back to the external-host treatment.
 */
export const MAX_FIRST_PARTY_HOST_PATTERNS = 100

/**
 * Reduce a team's first-party URL entries (recording domains and app URLs) to deduplicated
 * registrable-domain patterns; the anonymizer collapses matching hosts to `example.com`.
 */
export function firstPartyHostPatterns(firstPartyUrlEntries: string[] | null | undefined): string[] {
    const patterns: string[] = []
    for (const domain of firstPartyUrlEntries ?? []) {
        // The DB column allows NULL elements; one bad entry must not poison the team refresh.
        if (typeof domain !== 'string') {
            continue
        }
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
        const parsed = parseHostname(hostname, { allowPrivateDomains: true })
        if (parsed.domain !== null) {
            patterns.push(parsed.domain.toLowerCase())
            continue
        }
        // No registrable domain: keep bare machine names (`localhost`, `intranet`) and IPs, but
        // drop listed public suffixes (`com`, `co.uk`, a bare `github.io`) — a suffix pattern
        // would match every host under it.
        if (parsed.isIp || !(parsed.isIcann || parsed.isPrivate)) {
            patterns.push(hostname.toLowerCase())
        }
    }
    return [...new Set(patterns)].slice(0, MAX_FIRST_PARTY_HOST_PATTERNS)
}
