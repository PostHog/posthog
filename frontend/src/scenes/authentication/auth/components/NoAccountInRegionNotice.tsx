import { useValues } from 'kea'

import { Link } from 'lib/lemon-ui/Link'
import { countryCodeToFlag } from 'lib/utils/country'
import { otherRegionLoginUrl, otherRegionOf } from 'scenes/authentication/shared/OtherRegionHint'
import { pendingOAuthConnectionLogic } from 'scenes/authentication/shared/pendingOAuthConnectionLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

/**
 * Shown before an account is created, because a person who already uses PostHog in the other cloud
 * region gets "no account" here and would otherwise create a second, empty one. A pending OAuth
 * connection is pinned to this region, so the notice stays hidden for it.
 */
export function NoAccountInRegionNotice({ email }: { email: string }): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const { pendingConnection } = useValues(pendingOAuthConnectionLogic)

    if (!preflight?.cloud || !preflight.region || pendingConnection) {
        return null
    }

    const otherRegion = otherRegionOf(preflight.region)
    const search = new URLSearchParams(location.search)
    search.set('email', email)

    return (
        <div className="AuthScene__note mb-5 flex gap-3 items-start py-3 px-3.5 text-xs leading-relaxed text-secondary text-left border border-dashed rounded">
            <span className="text-base leading-none mt-0.5" aria-hidden>
                {countryCodeToFlag(otherRegion)}
            </span>
            <div className="flex-1 min-w-0">
                <p className="m-0">
                    <strong className="text-primary">No account here in the {preflight.region} region.</strong>{' '}
                    <span>Already using PostHog? Your account might live in the {otherRegion}.</span>
                </p>
                <Link
                    to={otherRegionLoginUrl(preflight.region, `?${search.toString()}`)}
                    disableClientSideRouting
                    data-attr="auth-no-account-switch-region"
                    className="inline-block mt-1 font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                >
                    Switch to {otherRegion} →
                </Link>
            </div>
        </div>
    )
}
