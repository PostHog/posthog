import { useActions, useValues } from 'kea'

import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { urls } from 'scenes/urls'

import { authLogic, hasSingleSignOn } from '../authLogic'
import { loginLogic } from '../loginLogic'

function noPasswordMessage(providerNames: string[]): string {
    if (!providerNames.length) {
        return "This account doesn't have a password yet."
    }
    const providers =
        providerNames.length > 2
            ? `${providerNames.slice(0, -1).join(', ')}, or ${providerNames.at(-1)}`
            : providerNames.join(' or ')
    return `This account doesn't have a password yet. Log in with ${providers} using this email address, or set a password.`
}

export function LoginPasswordField(): JSX.Element {
    const { accountExists, isLoginPasswordHidden } = useValues(authLogic)
    const {
        login,
        loginErrors,
        precheckResponse,
        hasNoConfiguredLoginMethod,
        autoRedirectingToProvider,
        instanceSocialProviders,
        setPasswordLinkSentTo,
        setPasswordLinkSentToLoading,
    } = useValues(loginLogic)
    const { setLoginValue, sendSetPasswordLink } = useActions(loginLogic)

    return (
        // `empty:hidden` drops the top padding for an SSO-only account, which has nothing to show here
        <div className="flex flex-col gap-4 pt-4 empty:hidden">
            {!isLoginPasswordHidden && (
                <LemonField.Pure
                    htmlFor="auth-login-password"
                    label={
                        <div className="flex items-baseline justify-between w-full">
                            <span>Password</span>
                            <Link
                                to={[urls.passwordReset(), { email: login.email }]}
                                data-attr="forgot-password"
                                className="text-xs font-semibold text-warning"
                                tabIndex={-1}
                            >
                                Forgot password?
                            </Link>
                        </div>
                    }
                    error={loginErrors.password}
                >
                    <LemonInput
                        id="auth-login-password"
                        className="ph-ignore-input"
                        data-attr="password"
                        type="password"
                        autoFocus
                        autoComplete="current-password"
                        value={login.password}
                        onChange={(value) => setLoginValue('password', value)}
                        status={loginErrors.password ? 'danger' : 'default'}
                        fullWidth
                    />
                </LemonField.Pure>
            )}
            {accountExists === false && !hasSingleSignOn(precheckResponse) && (
                <AuthBanner variant="note">
                    There's no account for this email. Ask your PostHog admin for an invite.
                </AuthBanner>
            )}
            {hasNoConfiguredLoginMethod &&
                (setPasswordLinkSentTo === login.email ? (
                    <AuthBanner variant="success">
                        <span>We sent a link to </span>
                        <strong>{login.email}</strong>
                        <span>. Open it to set your password, then log in.</span>
                    </AuthBanner>
                ) : (
                    <AuthBanner variant="warning">
                        <p className="mb-2">
                            {noPasswordMessage(instanceSocialProviders.map((p) => SSO_PROVIDER_NAMES[p]))}
                        </p>
                        <LemonButton
                            type="secondary"
                            size="small"
                            // Autocapture reports the click. Each reset entry point has its own
                            // `data-attr`, so one funnel can tell them apart.
                            data-attr="login-no-method-reset-password"
                            loading={setPasswordLinkSentToLoading}
                            onClick={() => sendSetPasswordLink(login.email)}
                        >
                            Email me a link to set a password
                        </LemonButton>
                    </AuthBanner>
                ))}
            {autoRedirectingToProvider && (
                <p className="text-sm text-secondary text-center mb-0">
                    Redirecting to {SSO_PROVIDER_NAMES[autoRedirectingToProvider]}…
                </p>
            )}
        </div>
    )
}
