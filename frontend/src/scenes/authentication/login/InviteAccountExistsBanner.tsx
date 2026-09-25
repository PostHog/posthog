import { useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { loginLogic } from './loginLogic'

export function InviteAccountExistsBanner({ className }: { className?: string }): JSX.Element | null {
    const { invitingOrganizationName, login } = useValues(loginLogic)

    if (!invitingOrganizationName) {
        return null
    }

    return (
        <LemonBanner type="info" className={className}>
            <span>{`You already have a PostHog account, so log in to join ${invitingOrganizationName}.`}</span>{' '}
            <Link
                to={[urls.passwordReset(), { email: login.email }]}
                data-attr="login-invite-account-exists-reset-password"
                className="font-semibold"
            >
                Forgot your password?
            </Link>
        </LemonBanner>
    )
}
