import { IncomingMessage } from 'http'
import { isIP } from 'net'

import { GeoIp } from '~/common/utils/geoip'

export const REGION_BLOCKED_MESSAGE =
    'PostHog is not available in your region. If you think this is in error, please contact tim@posthog.com.'

export type RegionBlockCheck = (req: IncomingMessage) => boolean

/** Matches Django's `_normalize_ip`: strips a port, and returns undefined for anything that isn't an IP. */
export function normalizeIp(raw: string): string | undefined {
    let ip = raw.trim()
    if (ip.startsWith('[')) {
        const end = ip.indexOf(']')
        if (end !== -1) {
            ip = ip.slice(1, end)
        }
    } else if (ip.split(':').length === 2) {
        ip = ip.split(':')[0]
    }
    return isIP(ip) ? ip : undefined
}

/** The left-most X-Forwarded-For entry, as Django reads it with TRUST_ALL_PROXIES. */
export function clientIp(req: IncomingMessage): string | undefined {
    const header = req.headers['x-forwarded-for']
    const forwarded = (Array.isArray(header) ? header.join(',') : (header ?? ''))
        .split(',')
        .map((part) => part.trim())
        .filter(Boolean)
    const raw = forwarded[0] ?? req.socket.remoteAddress
    return raw ? normalizeIp(raw) : undefined
}

/** Django's AllowIPMiddleware decision for BLOCKED_GEOIP_REGIONS. An address that cannot be read is
 * blocked, and an address the GeoIP database cannot place is allowed. */
export function createRegionBlockCheck(blockedCountries: string[], geoip: GeoIp | undefined): RegionBlockCheck {
    const blocked = new Set(blockedCountries.map((code) => code.trim().toUpperCase()).filter(Boolean))
    if (blocked.size === 0) {
        return () => false
    }
    return (req) => {
        const ip = clientIp(req)
        if (!ip) {
            return true
        }
        const country = geoip?.city(ip)?.country?.isoCode
        return country !== undefined && blocked.has(country)
    }
}
