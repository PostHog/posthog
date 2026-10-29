import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { usePrevious } from 'lib/hooks/usePrevious'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { isWebKitBrowser } from 'lib/utils/dom'
import { isEmail } from 'lib/utils/url'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { RegionField } from 'scenes/authentication/shared/authScene/RegionField'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { authLogic } from '../authLogic'
import { EmailStepSocialButtons } from '../components/EmailStepSocialButtons'
import { EmailStepTitle } from '../components/EmailStepTitle'
import { LoginErrorBanner } from '../components/LoginErrorBanner'
import { LoginPasswordField } from '../components/LoginPasswordField'
import { LoginSignupLink } from '../components/LoginSignupLink'
import { LoginSingleSignOnButtons } from '../components/LoginSingleSignOnButtons'
import { OtherRegionNotice } from '../components/OtherRegionNotice'
import { SessionRiskBanner } from '../components/SessionRiskBanner'
import { SignupPasswordField } from '../components/SignupPasswordField'
import { loginLogic } from '../loginLogic'
import { signupLogic } from '../signupLogic'

/**
 * The email card. It also renders the `login` and `signup_credentials` steps, so once the precheck
 * answers, the password for that path opens under the email field instead of on a new screen.
 */
export function EmailStep(): JSX.Element {
    const { login, precheckResponse, generalError, isLoginSubmitting } = useValues(loginLogic)
    const { setLoginValue, precheck, submitLogin } = useActions(loginLogic)
    const { entry, step, emailError, isEmailSubmitting, isLoginPasswordHidden } = useValues(authLogic)
    const { continueWithEmail, chooseAccountPath } = useActions(authLogic)
    const { signupEmailTaken, signupEmail, validatedPassword, passkeyRegistered, isSignupPanelAuthSubmitting } =
        useValues(signupLogic)
    const { submitSignupPanelAuth } = useActions(signupLogic)
    const { preflight } = useValues(preflightLogic)
    const prevEmail = usePrevious(login.email)
    const [showJoinOrg, setShowJoinOrg] = useState(false)

    // An autofilled address is prechecked at once, so a passkey prompt can open before Continue
    useEffect(() => {
        const charDelta = login.email.length - (prevEmail?.length ?? 0)
        const isAutofill = charDelta > 1

        if (isAutofill && isEmail(login.email, { requireTLD: true }) && precheckResponse.status === 'pending') {
            precheck({ email: login.email })
        }
    }, [login.email, prevEmail, precheckResponse.status, precheck])

    const termsFooter = (
        <p className="AuthScene__terms mt-5 mb-0 text-xs leading-relaxed text-tertiary text-center">
            <span>By creating an account, you agree to our</span>{' '}
            <Link to="https://posthog.com/terms" target="_blank">
                Terms of Service ↗
            </Link>{' '}
            <span>and</span>{' '}
            <Link to="https://posthog.com/privacy" target="_blank">
                Privacy Policy ↗
            </Link>
            <span>.</span>
        </p>
    )

    return (
        <AuthSceneCard footer={step === 'signup_credentials' ? termsFooter : undefined} showPendingConnection>
            <EmailStepTitle />
            <SessionRiskBanner className="mb-4" />
            <LoginErrorBanner />
            {step === 'login' && generalError?.code === 'invalid_credentials' && (
                <OtherRegionNotice email={login.email} reason="login_failed" />
            )}
            <form
                className="flex flex-col gap-4"
                noValidate
                onSubmit={(e) => {
                    e.preventDefault()
                    if (step === 'login') {
                        submitLogin()
                    } else if (step === 'signup_credentials') {
                        submitSignupPanelAuth()
                    } else {
                        continueWithEmail()
                    }
                }}
            >
                <RegionField />
                <div className="flex flex-col">
                    <LemonField.Pure label="Email" htmlFor="auth-email" error={emailError}>
                        <LemonInput
                            id="auth-email"
                            className="ph-ignore-input"
                            // pinned: Playwright and autocapture select these per entry URL
                            data-attr={entry === 'signup' ? 'signup-email' : 'login-email'}
                            type="email"
                            autoFocus
                            placeholder="you@yourcompany.com"
                            // The `webauthn` token enables passkey autofill (conditional UI),
                            // which we only offer on WebKit; elsewhere the auto-modal handles passkeys.
                            autoComplete={isWebKitBrowser() ? 'username webauthn' : 'username'}
                            value={login.email}
                            onChange={(value) => setLoginValue('email', value)}
                            status={emailError ? 'danger' : 'default'}
                            fullWidth
                        />
                    </LemonField.Pure>
                    <AnimatedCollapsible collapsed={step === 'email'} autoHeight>
                        {step === 'login' ? (
                            <LoginPasswordField />
                        ) : step === 'signup_credentials' ? (
                            <SignupPasswordField />
                        ) : (
                            <></>
                        )}
                    </AnimatedCollapsible>
                </div>
                {signupEmailTaken && (
                    <p className="-mt-2 mb-0 text-sm text-secondary">
                        <Link
                            onClick={() => chooseAccountPath('login', true)}
                            data-attr="auth-email-taken-login"
                            className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                        >
                            Log in instead
                        </Link>
                        <span>
                            . Signed up with a version of this address with dots or a +tag? Log in with that one.
                        </span>
                    </p>
                )}
                {step === 'login' ? (
                    !isLoginPasswordHidden && (
                        <LemonButton
                            type="primary"
                            size="large"
                            center
                            fullWidth
                            htmlType="submit"
                            data-attr="password-login"
                            loading={isLoginSubmitting}
                        >
                            Log in
                        </LemonButton>
                    )
                ) : step === 'signup_credentials' ? (
                    <LemonButton
                        type="primary"
                        size="large"
                        center
                        fullWidth
                        htmlType="submit"
                        // pinned: Playwright and the signup funnel select the account creation submit by this
                        data-attr="signup-auth-continue"
                        loading={isSignupPanelAuthSubmitting}
                        disabledReason={
                            !passkeyRegistered && validatedPassword.feedback ? validatedPassword.feedback : undefined
                        }
                    >
                        Create account
                    </LemonButton>
                ) : (
                    <LemonButton
                        type="primary"
                        size="large"
                        center
                        fullWidth
                        htmlType="submit"
                        // pinned: `signup-start` is the signup funnel's existing first-step attribute
                        data-attr={entry === 'signup' ? 'signup-start' : 'login-email-continue'}
                        loading={isEmailSubmitting}
                    >
                        Continue
                    </LemonButton>
                )}
                {step === 'login' && <LoginSingleSignOnButtons />}
                {step === 'signup_credentials' && <OtherRegionNotice email={signupEmail} reason="no_account" />}
            </form>
            {step === 'login' && <LoginSignupLink />}
            <EmailStepSocialButtons />
            {step === 'email' && entry === 'signup' && !preflight?.demo && (
                <div className="mt-4 text-center">
                    <button
                        type="button"
                        data-attr="signup-join-existing-org"
                        className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-secondary text-xs"
                        onClick={() => setShowJoinOrg((v) => !v)}
                    >
                        Trying to join an existing organization?
                    </button>
                    {showJoinOrg && (
                        <AuthBanner variant="note" className="mt-3">
                            You'll need your invite link. When a teammate invites you, we email you a personal link.
                            Didn't get one? Check spam, or ask them to resend it from their members settings.
                        </AuthBanner>
                    )}
                </div>
            )}
        </AuthSceneCard>
    )
}
