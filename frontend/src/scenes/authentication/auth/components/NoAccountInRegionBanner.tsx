import { useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { otherRegionLoginUrl, otherRegionOf } from 'scenes/authentication/shared/OtherRegionHint'
import { pendingOAuthConnectionLogic } from 'scenes/authentication/shared/pendingOAuthConnectionLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

/**
 * Shown before an account is created, because a person who already uses PostHog in the other cloud
 * region gets "no account" here and would otherwise create a second, empty one. A pending OAuth
 * connection is pinned to this region, so the banner stays hidden for it.
 */
export function NoAccountInRegionBanner({ email }: { email: string }): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { pendingConnection } = useValues(pendingOAuthConnectionLogic)

    if (!preflight?.cloud || !preflight.region || pendingConnection) {
        return null
    }

    const otherRegion = otherRegionOf(preflight.region)
    const search = new URLSearchParams(location.search)
    search.set('email', email)

    return (
        <LemonBanner
            type="warning"
            className="mb-4"
            action={{
                children: `Switch to ${otherRegion}`,
                to: otherRegionLoginUrl(preflight.region, `?${search.toString()}`),
                disableClientSideRouting: true,
                'data-attr': 'auth-no-account-switch-region',
            }}
        >
            <span>No account uses this email in the {preflight.region} region.</span>{' '}
            <span>If you already use PostHog, your account may be in the {otherRegion} region.</span>
        </LemonBanner>
    )
}
