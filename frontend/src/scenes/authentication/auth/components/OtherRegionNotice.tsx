import clsx from 'clsx'
import { useValues } from 'kea'

import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { countryCodeToFlag } from 'lib/utils/country'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { otherRegionLoginUrl, otherRegionOf } from 'scenes/authentication/shared/otherRegion'
import { pendingOAuthConnectionLogic } from 'scenes/authentication/shared/pendingOAuthConnectionLogic'

/** `no_account` shows before an account is created. `login_failed` shows after a rejected password. */
export type OtherRegionReason = 'no_account' | 'login_failed'

// pinned: autocapture `data-attr` values, `other-region-login` predates this page
const SWITCH_DATA_ATTR: Record<OtherRegionReason, string> = {
    no_account: 'auth-no-account-switch-region',
    login_failed: 'other-region-login',
}

/**
 * A person who already uses PostHog in the other cloud region gets "no account" or "wrong
 * password" here, and could otherwise create a second, empty account. Most new people are in the
 * right region, so before signup this is one small line. After a rejected password it is a banner.
 * A pending OAuth connection is pinned to this region, so the notice stays hidden for it.
 */
export function OtherRegionNotice({
    email,
    reason,
    className,
}: {
    email: string
    reason: OtherRegionReason
    className?: string
}): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { pendingConnection } = useValues(pendingOAuthConnectionLogic)

    if (!preflight?.cloud || !preflight.region || pendingConnection) {
        return null
    }

    const otherRegion = otherRegionOf(preflight.region)
    const search = new URLSearchParams(location.search)
    search.set('email', email)
    const switchUrl = otherRegionLoginUrl(preflight.region, `?${search.toString()}`)

    if (reason === 'no_account') {
        return (
            <p className={clsx('m-0 text-xs text-secondary text-center', className)}>
                <span>Already have an account? Maybe it's in our</span>{' '}
                <Link
                    to={switchUrl}
                    disableClientSideRouting
                    data-attr={SWITCH_DATA_ATTR[reason]}
                    className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                >
                    {countryCodeToFlag(otherRegion)} {otherRegion} region
                </Link>
                <span>?</span>
            </p>
        )
    }

    return (
        <AuthBanner variant="note" className={clsx('mb-5', className)} icon={countryCodeToFlag(otherRegion)}>
            <p className="m-0">
                <strong className="text-primary">Wrong region, maybe?</strong>{' '}
                <span>Your account might live in the {otherRegion}.</span>
            </p>
            <Link
                to={switchUrl}
                disableClientSideRouting
                data-attr={SWITCH_DATA_ATTR[reason]}
                className="inline-block mt-1 font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
            >
                Switch to {otherRegion} →
            </Link>
        </AuthBanner>
    )
}
