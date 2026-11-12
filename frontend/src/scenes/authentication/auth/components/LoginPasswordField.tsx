import { useActions, useValues } from 'kea'

import { SSO_PROVIDER_NAMES } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { urls } from 'scenes/urls'

import { authLogic, hasSingleSignOn } from '../authLogic'
import { loginLogic } from '../loginLogic'
import { LoginTurnstileWidget } from './LoginTurnstileWidget'

export function LoginPasswordField(): JSX.Element {
    const { accountExists, isLoginPasswordHidden } = useValues(authLogic)
    const {
        login,
        loginErrors,
        precheckResponse,
        hasNoConfiguredLoginMethod,
        autoRedirectingToProvider,
        setPasswordLinkSentTo,
        preflight,
        turnstileWidgetKey,
    } = useValues(loginLogic)
    const { setLoginValue } = useActions(loginLogic)

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
            {!isLoginPasswordHidden && precheckResponse.turnstile_site_key && (
                <LoginTurnstileWidget
                    key={`${precheckResponse.email}-${turnstileWidgetKey}`}
                    siteKey={precheckResponse.turnstile_site_key}
                />
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
                        <strong className="break-all">{login.email}</strong>
                        <span>. Open it to set your password, then log in.</span>
                    </AuthBanner>
                ) : preflight?.email_service_available ? (
                    <AuthBanner variant="warning">
                        This account doesn't have a password yet. Log in with one of the options below, or get an email
                        to set a password.
                    </AuthBanner>
                ) : (
                    <AuthBanner variant="warning">
                        <span>This account doesn't have a password yet, and this instance can't send email. </span>
                        <Link to={[urls.passwordReset(), { email: login.email }]} data-attr="login-no-method-no-email">
                            See how to get access
                        </Link>
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
