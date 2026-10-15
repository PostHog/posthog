import { createHmac, timingSafeEqual } from 'crypto'
import { IncomingMessage } from 'http'
import { isIP } from 'net'
import { Counter } from 'prom-client'

import { GeoIp } from '~/common/utils/geoip'

export const REGION_BLOCKED_MESSAGE =
    'PostHog is not available in your region. If you think this is in error, please contact tim@posthog.com.'

export type RegionBlockCheck = (req: IncomingMessage) => boolean

const SIGNED_CLIENT_IP_MAX_AGE_SECONDS = 60
const SIGNED_CLIENT_IP_MAX_CLOCK_SKEW_SECONDS = 5

const signedClientIpCounter = new Counter({
    name: 'push_subscription_managed_proxy_client_ip_total',
    help: 'Verifications of the client IP the managed reverse proxy signs, by outcome.',
    labelNames: ['outcome'],
})

function header(req: IncomingMessage, name: string): string | undefined {
    const value = req.headers[name]
    return Array.isArray(value) ? value[0] : value
}

/** Django's `verify_signed_client_ip`: the managed proxy sends hex(HMAC-SHA256(key, "<ip>:<unix seconds>")).
 * Envoy sets X-Forwarded-For to the Cloudflare edge for that traffic, so only this signature recovers
 * the real client. */
export function signedClientIp(
    req: IncomingMessage,
    signingKeys: string[],
    nowSeconds: number = Date.now() / 1000
): string | undefined {
    const ip = header(req, 'x-posthog-client-ip')
    const timestamp = header(req, 'x-posthog-client-ip-timestamp')
    const signature = header(req, 'x-posthog-client-ip-signature')
    if (ip === undefined && timestamp === undefined && signature === undefined) {
        return undefined
    }
    const outcome = verifySignature(ip, timestamp, signature, signingKeys, nowSeconds)
    signedClientIpCounter.inc({ outcome })
    return outcome === 'valid' ? ip : undefined
}

function verifySignature(
    ip: string | undefined,
    timestamp: string | undefined,
    signature: string | undefined,
    signingKeys: string[],
    nowSeconds: number
): string {
    const keys = signingKeys.filter(Boolean)
    if (keys.length === 0) {
        return 'not_configured'
    }
    if (!ip || !timestamp || !signature || !/^\d{1,12}$/.test(timestamp) || !isIP(ip)) {
        return 'invalid_input'
    }
    const age = nowSeconds - Number(timestamp)
    if (age < -SIGNED_CLIENT_IP_MAX_CLOCK_SKEW_SECONDS || age > SIGNED_CLIENT_IP_MAX_AGE_SECONDS) {
        return 'timestamp_out_of_window'
    }
    const provided = Buffer.from(signature.toLowerCase())
    for (const key of keys) {
        const expected = Buffer.from(createHmac('sha256', key).update(`${ip}:${timestamp}`).digest('hex'))
        if (expected.length === provided.length && timingSafeEqual(expected, provided)) {
            return 'valid'
        }
    }
    return 'bad_signature'
}

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

/** The managed proxy's signed client IP when it verifies, otherwise the left-most X-Forwarded-For
 * entry, as Django reads it with TRUST_ALL_PROXIES. That entry is only trustworthy because the Cloud
 * ingress overwrites the header. Behind a proxy that appends to it, the client controls the entry. */
export function clientIp(req: IncomingMessage, signingKeys: string[] = []): string | undefined {
    const signed = signedClientIp(req, signingKeys)
    if (signed) {
        return normalizeIp(signed)
    }
    const forwardedFor = req.headers['x-forwarded-for']
    const forwarded = (Array.isArray(forwardedFor) ? forwardedFor.join(',') : (forwardedFor ?? ''))
        .split(',')
        .map((part) => part.trim())
        .filter(Boolean)
    const raw = forwarded[0] ?? req.socket.remoteAddress
    return raw ? normalizeIp(raw) : undefined
}

/** Django's AllowIPMiddleware decision for BLOCKED_GEOIP_REGIONS. An address that cannot be read is
 * blocked, and an address the GeoIP database cannot place is allowed. */
export function createRegionBlockCheck(
    blockedCountries: string[],
    geoip: GeoIp | undefined,
    signingKeys: string[] = []
): RegionBlockCheck {
    const blocked = new Set(blockedCountries.map((code) => code.trim().toUpperCase()).filter(Boolean))
    if (blocked.size === 0) {
        return () => false
    }
    return (req) => {
        const ip = clientIp(req, signingKeys)
        if (!ip) {
            return true
        }
        const country = geoip?.city(ip)?.country?.isoCode
        return country !== undefined && blocked.has(country)
    }
}
