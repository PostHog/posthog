import { Request } from 'ultimate-express'

/**
 * Pull the application host from the request, validating it against the configured
 * `.agents.posthog.com`-shaped suffix. Returns the full hostname (subdomain + suffix),
 * since the internal resolve endpoint matches on the full domain.
 */
export function extractHost(req: Request, domainSuffix: string): string | null {
    // Honor an explicit override header for clients that proxy us, but fall back to Host.
    const raw = (req.header('x-original-host') ?? req.hostname ?? '').toLowerCase().trim()
    if (!raw) {
        return null
    }
    if (!raw.endsWith(domainSuffix.toLowerCase())) {
        return null
    }
    return raw
}
