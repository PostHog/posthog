import { useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

/**
 * Hint for users provisioned through the Vercel marketplace. Those accounts are created without a
 * password and unverified (ee/vercel/integration.py), and this page offers no "Login with Vercel"
 * affordance — Vercel SSO is Vercel-initiated only. The password reset flow both sets a password
 * and verifies their email, so it's the canonical way back in; this surfaces that recovery path.
 *
 * Shown unconditionally on cloud whenever it's rendered (i.e. on a failed login) — it never checks
 * whether the email actually belongs to a Vercel account, so it cannot be used to probe for account
 * existence.
 */
export function VercelLoginHint({ email }: { email?: string }): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    if (!preflight?.cloud) {
        return null
    }

    return (
        <LemonBanner type="info">
            Signed up through the Vercel marketplace? Your account doesn't have a password yet.{' '}
            <Link to={[urls.passwordReset(), { email: email ?? '' }]} data-attr="vercel-login-set-password">
                Set a password
            </Link>{' '}
            to finish setting up and log in.
        </LemonBanner>
    )
}
