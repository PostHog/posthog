import { Link } from 'lib/lemon-ui/Link'

// Login error copy shared by the auth login variants and the exporter login screen.
export const ERROR_MESSAGES: Record<string, string | JSX.Element> = {
    no_new_organizations:
        'Your email address is not associated with an account. Please ask your administrator for an invite.',
    invalid_sso_provider: (
        <>
            The SSO provider you specified is invalid. Visit{' '}
            <Link to="https://posthog.com/sso" target="_blank">
                https://posthog.com/sso
            </Link>{' '}
            for details.
        </>
    ),
    improperly_configured_sso: (
        <>
            Cannot login with SSO provider because the provider is not configured, or your instance does not have the
            required license. Please visit{' '}
            <Link to="https://posthog.com/sso" target="_blank">
                https://posthog.com/sso
            </Link>{' '}
            for details.
        </>
    ),
    jit_not_enabled:
        'We could not find an account with your email address and your organization does not support automatic enrollment. Please contact your administrator for an invite.',
    saml_sso_enforced:
        'Your organization requires SAML SSO authentication. Please enter your email address to access your account.',
    google_sso_enforced: 'Your organization does not allow this authentication method. Please log in with Google.',
    github_sso_enforced: 'Your organization does not allow this authentication method. Please log in with GitHub.',
    gitlab_sso_enforced: 'Your organization does not allow this authentication method. Please log in with GitLab.',
    // our catch-all case, so the message is generic
    sso_enforced: "Please log in with your organization's required SSO method.",
    oauth_cancelled: "Sign in was cancelled. Please try again when you're ready.",
    invalid_invite:
        'This invite link is no longer valid. It may have expired or been revoked. Please ask your administrator for a new invite.',
    social_login_failure: 'Login failed. Please try again or contact your administrator.',
}
