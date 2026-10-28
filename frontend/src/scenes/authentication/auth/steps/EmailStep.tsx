import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { SocialLoginButtons } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { usePrevious } from 'lib/hooks/usePrevious'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { isWebKitBrowser } from 'lib/utils/dom'
import { isEmail } from 'lib/utils/url'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { RegionField } from 'scenes/authentication/shared/authScene/RegionField'
import { useLastLoginMethod } from 'scenes/authentication/shared/lastLoginMethod'
import { pendingOAuthConnectionLogic } from 'scenes/authentication/shared/pendingOAuthConnectionLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { authLogic } from '../authLogic'
import { ConnectTitle } from '../components/ConnectTitle'
import { HighlightedName } from '../components/HighlightedName'
import { LoginErrorBanner } from '../components/LoginErrorBanner'
import { SessionRiskBanner } from '../components/SessionRiskBanner'
import { loginLogic } from '../loginLogic'
import { signupLogic } from '../signupLogic'

function EmailStepTitle(): JSX.Element {
    const { entry } = useValues(authLogic)
    const { pendingConnection } = useValues(pendingOAuthConnectionLogic)
    const isReturning = useLastLoginMethod() !== null

    if (pendingConnection) {
        return (
            <AuthCardTitle
                title={<ConnectTitle lead="Log in or sign up to connect" clientName={pendingConnection.clientName} />}
                sub={`${pendingConnection.clientName} saved you a seat.`}
            />
        )
    }
    if (entry === 'signup') {
        return <AuthCardTitle title="Get started" sub="Make your product self-driving." />
    }
    return (
        <AuthCardTitle
            title={
                <>
                    <span>{isReturning ? 'Log in to ' : 'Log in or sign up to '}</span>
                    <HighlightedName>@PostHog</HighlightedName>
                </>
            }
            sub={isReturning ? "Welcome back. Let's go ship something." : 'Hedgehogs of all kinds welcome.'}
        />
    )
}

export function EmailStep(): JSX.Element {
    const { login, precheckResponse } = useValues(loginLogic)
    const { setLoginValue, precheck } = useActions(loginLogic)
    const { entry, emailError, isEmailSubmitting } = useValues(authLogic)
    const { continueWithEmail, chooseAccountPath } = useActions(authLogic)
    const { signupEmailTaken } = useValues(signupLogic)
    const { preflight } = useValues(preflightLogic)
    const lastLoginMethod = useLastLoginMethod()
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

    return (
        <AuthSceneCard showPendingConnection>
            <EmailStepTitle />
            <SessionRiskBanner className="mb-4" />
            <LoginErrorBanner />
            <form
                className="flex flex-col gap-4"
                noValidate
                onSubmit={(e) => {
                    e.preventDefault()
                    continueWithEmail()
                }}
            >
                <RegionField />
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
            </form>
            {!preflight?.demo && (
                <SocialLoginButtons
                    topDivider
                    caption="or continue with"
                    captionLocation="top"
                    lastUsedProvider={lastLoginMethod}
                    showPasskey={entry === 'login'}
                />
            )}
            {entry === 'signup' && !preflight?.demo && (
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
