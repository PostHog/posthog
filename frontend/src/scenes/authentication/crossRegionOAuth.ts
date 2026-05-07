import { Region } from '~/types'

/**
 * First-party OAuth applications are registered with the same client name
 * on both US and EU PostHog Cloud instances, but they have different
 * client_ids in each region's database. When a user is in the middle of
 * an OAuth flow on /login?next=/oauth/authorize?client_id=... and switches
 * the data region with <RegionSelect />, we need to translate the
 * region-specific client_id (and any matching redirect_uri) inside the
 * `next` URL — otherwise the destination region's server rejects the
 * request with "Invalid client_id".
 *
 * Keep these in sync with:
 *   - apps/code/src/shared/constants/oauth.ts in posthog/code
 *   - posthog/temporal/oauth.py
 *   - the OAuth proxy KV mappings at oauth.posthog.com
 *
 * Only first-party PostHog apps belong here. Third-party clients should
 * be re-initialized from the source app rather than rewritten.
 */
type CrossRegionClientMapping = {
    [Region.US]: string
    [Region.EU]: string
}

const CROSS_REGION_CLIENT_MAPPINGS: CrossRegionClientMapping[] = [
    {
        // PostHog Code (desktop app)
        [Region.US]: 'HCWoE0aRFMYxIxFNTTwkOORn5LBjOt2GVDzwSw5W',
        [Region.EU]: 'AIvijgMS0dxKEmr5z6odvRd8Pkh5vts3nPTzgzU9',
    },
]

function findMappingByClientId(clientId: string): CrossRegionClientMapping | null {
    for (const mapping of CROSS_REGION_CLIENT_MAPPINGS) {
        if (mapping[Region.US] === clientId || mapping[Region.EU] === clientId) {
            return mapping
        }
    }
    return null
}

/**
 * Translate a client_id from one region to another for known first-party
 * cross-region apps. Returns the original client_id if no mapping is found
 * (third-party clients, unknown clients, etc.).
 */
export function translateClientIdForRegion(clientId: string, targetRegion: Region): string {
    const mapping = findMappingByClientId(clientId)
    if (!mapping) {
        return clientId
    }
    return mapping[targetRegion]
}

/**
 * Given the current location (pathname + search + hash), produce a URL on
 * the target region's host that preserves the OAuth flow. In particular,
 * if the URL targets /oauth/authorize/ directly, or carries a
 * `next=/oauth/authorize/...` (the typical login -> oauth chain), rewrite
 * the embedded `client_id` to the target region's equivalent for known
 * first-party apps.
 *
 * This is best-effort: any unrecognized client_id is left untouched and
 * the user will see the upstream "Invalid client_id" error, which is
 * already the existing behavior.
 */
export function buildRegionSwitchUrl({
    targetHost,
    pathname,
    search,
    hash,
    targetRegion,
}: {
    targetHost: string
    pathname: string
    search: string
    hash: string
    targetRegion: Region
}): string {
    const rewrittenSearch = rewriteOAuthSearchParams(pathname, search, targetRegion)
    return `https://${targetHost}${pathname}${rewrittenSearch}${hash}`
}

function rewriteOAuthSearchParams(pathname: string, search: string, targetRegion: Region): string {
    if (!search) {
        return search
    }
    const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)

    const isOAuthAuthorize = pathname === '/oauth/authorize' || pathname === '/oauth/authorize/'

    if (isOAuthAuthorize) {
        const clientId = params.get('client_id')
        if (clientId) {
            const translated = translateClientIdForRegion(clientId, targetRegion)
            if (translated !== clientId) {
                params.set('client_id', translated)
            }
        }
    }

    // /login?next=/oauth/authorize?client_id=... is the most common path; the
    // backend bounces unauthenticated users from /oauth/authorize to /login
    // with the original URL encoded as `next`. Rewrite that too so the post-
    // login redirect lands on a valid client_id for the new region.
    const next = params.get('next')
    if (next) {
        const rewrittenNext = rewriteEmbeddedNext(next, targetRegion)
        if (rewrittenNext !== next) {
            params.set('next', rewrittenNext)
        }
    }

    const rebuilt = params.toString()
    return rebuilt ? `?${rebuilt}` : ''
}

function rewriteEmbeddedNext(nextValue: string, targetRegion: Region): string {
    // `next` is a relative path with its own query string, e.g.
    //   /oauth/authorize?client_id=...&redirect_uri=...
    // Splitting by '?' is sufficient here since `next` cannot contain a host.
    const [path, ...rest] = nextValue.split('?')
    if (!rest.length) {
        return nextValue
    }
    if (path !== '/oauth/authorize' && path !== '/oauth/authorize/') {
        return nextValue
    }
    const params = new URLSearchParams(rest.join('?'))
    const clientId = params.get('client_id')
    if (!clientId) {
        return nextValue
    }
    const translated = translateClientIdForRegion(clientId, targetRegion)
    if (translated === clientId) {
        return nextValue
    }
    params.set('client_id', translated)
    return `${path}?${params.toString()}`
}
