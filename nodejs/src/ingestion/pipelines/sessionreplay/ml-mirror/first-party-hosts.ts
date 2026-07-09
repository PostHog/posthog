import { parse as parseHostname } from 'tldts'

/**
 * Reduce a team's recording domains to registrable-domain patterns; the anonymizer collapses
 * matching hosts to `example.com`.
 */
export function firstPartyHostPatterns(recordingDomains: string[] | null | undefined): string[] {
    const patterns: string[] = []
    for (const domain of recordingDomains ?? []) {
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
    return patterns
}
