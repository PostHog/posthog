import { useValues } from 'kea'

import { CLOUD_HOSTNAMES } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { Region } from '~/types'

export function otherRegionOf(region: Region): Region {
    return region === Region.US ? Region.EU : Region.US
}

// Preserve the query string (e.g. `next`) but always land on the login page of the other region.
export function otherRegionLoginUrl(region: Region, search: string): string {
    return `https://${CLOUD_HOSTNAMES[otherRegionOf(region)]}/login${search}`
}

/**
 * Region-aware hint for users who may be authenticating on the wrong PostHog Cloud region (US vs EU).
 *
 * Shown unconditionally whenever it's rendered on cloud — it never checks whether an account actually
 * exists on the other region, so it cannot be used to probe for account existence across regions.
 */
export function OtherRegionHint(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    if (!preflight?.cloud || !preflight?.region) {
        return null
    }

    const otherRegion = otherRegionOf(preflight.region)

    return (
        <LemonBanner type="info">
            Already have a PostHog Cloud account? It may live in our {otherRegion} region. You're currently on{' '}
            {preflight.region}.{' '}
            <Link
                to={otherRegionLoginUrl(preflight.region, location.search)}
                disableClientSideRouting
                data-attr="other-region-login"
            >
                Log in on {CLOUD_HOSTNAMES[otherRegion]}
            </Link>
        </LemonBanner>
    )
}
