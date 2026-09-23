import { useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { loginLogic } from './loginLogic'

export function InviteAccountExistsBanner({ className }: { className?: string }): JSX.Element | null {
    const { invitingOrganizationName, login } = useValues(loginLogic)

    if (invitingOrganizationName === null) {
        return null
    }

    return (
        <LemonBanner type="info" className={className}>
            <span>
                {invitingOrganizationName
                    ? `You already have a PostHog account, so log in to join ${invitingOrganizationName}.`
                    : 'You already have a PostHog account, so log in to accept your invite.'}
            </span>{' '}
            <Link
                to={[urls.passwordReset(), { email: login.email }]}
                // Autocapture reports the click. Each reset entry point has its own `data-attr`, so
                // one funnel can tell them apart.
                data-attr="login-invite-account-exists-reset-password"
                className="font-semibold"
            >
                Forgot your password?
            </Link>
        </LemonBanner>
    )
}
