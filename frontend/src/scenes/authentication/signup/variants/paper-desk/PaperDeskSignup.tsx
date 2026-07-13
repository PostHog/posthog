import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useState } from 'react'

import { getCookie } from 'lib/api'
import PasswordStrength from 'lib/components/PasswordStrength'
import SignupReferralSource from 'lib/components/SignupReferralSource'
import SignupRoleSelect from 'lib/components/SignupRoleSelect'
import passkeyLogo from 'lib/components/SocialLoginButton/passkey.svg'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { CardTitle } from 'scenes/authentication/shared/paperDesk/CardTitle'
import { PaperDeskCard, PaperDeskScene } from 'scenes/authentication/shared/paperDesk/PaperDeskScene'
import { RegionField } from 'scenes/authentication/shared/paperDesk/RegionField'
import { TurnstileChallenge } from 'scenes/authentication/signup/signupForm/TurnstileChallenge'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { LoginMethod } from '~/types'

import { signupLogic } from '../../signupForm/signupLogic'

const NOTES: Record<number, string[]> = {
    0: ['// create an account', '// 1M events free, every month'],
    1: ['// step 2 of 2', '// make it a good one'],
    2: ['// almost there', '// last step'],
}

/** Step 1 — email (+ region, social, pending-invite branch). */
function SignupEmailPanel(): JSX.Element {
    const { isSignupPanelEmailSubmitting, signupPanelEmailManualErrors, pendingInvite, loginUrl, emailCaseNotice } =
        useValues(signupLogic)
    const { preflight } = useValues(preflightLogic)
    const [showJoinOrg, setShowJoinOrg] = useState(false)
    const lastLoginMethod = getCookie('ph_last_login_method') as LoginMethod | null
    const accountExists = !!signupPanelEmailManualErrors?.email

    if (pendingInvite) {
        return <PendingInvitePanel />
    }

    const footer = preflight?.demo ? undefined : (
        <p className="mt-5 mb-0 text-sm text-secondary text-center">
            Already have an account?{' '}
            <Link
                to={loginUrl}
                data-attr="signup-login-link"
                className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
            >
                Log in →
            </Link>
        </p>
    )

    return (
        <PaperDeskCard footer={footer}>
            <CardTitle title="Get started" sub="Make your product self-driving." />
            <Form logic={signupLogic} formKey="signupPanelEmail" enableFormOnSubmit className="flex flex-col gap-4">
                <RegionField />
                <LemonField
                    name="email"
                    label="Email"
                    help={emailCaseNotice && <span className="text-warning">{emailCaseNotice}</span>}
                >
                    {({ value, onChange, error, id }) => (
                        <LemonInput
                            id={id}
                            className="ph-ignore-input"
                            data-attr="signup-email"
                            type="email"
                            autoFocus
                            autoComplete="email"
                            placeholder="you@yourcompany.com"
                            value={value ?? ''}
                            onChange={onChange}
                            status={error ? 'danger' : 'default'}
                            fullWidth
                        />
                    )}
                </LemonField>
                {accountExists && (
                    <p className="text-xs text-danger -mt-2">
                        <Link
                            to={loginUrl}
                            className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                        >
                            Log in instead →
                        </Link>
                    </p>
                )}
                <LemonButton
                    type="primary"
                    size="large"
                    center
                    fullWidth
                    htmlType="submit"
                    data-attr="signup-start"
                    loading={isSignupPanelEmailSubmitting}
                >
                    Continue
                </LemonButton>
            </Form>
            {!preflight?.demo && (
                <SocialLoginButtons
                    topDivider
                    caption="or sign up with"
                    lastUsedProvider={lastLoginMethod ?? undefined}
                    captionLocation="top"
                />
            )}
            {!preflight?.demo && (
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
                        <p className="PaperDesk__note mt-3 py-3 px-3.5 text-xs leading-relaxed text-secondary text-left bg-[#fbfbf9] border border-dashed border-[#c5c6bd] rounded">
                            You'll need your invite link. When a teammate invites you, we email you a personal link.
                            Didn't get one? Check spam, or ask them to resend it from their members settings.
                        </p>
                    )}
                </div>
            )}
        </PaperDeskCard>
    )
}

function PendingInvitePanel(): JSX.Element {
    const { signupPanelEmail, pendingInvite, pendingInviteResent, isPendingInviteResending } = useValues(signupLogic)
    const { resendPendingInvite, dismissPendingInvite } = useActions(signupLogic)
    const org = pendingInvite?.organization_name ?? 'your team'

    return (
        <PaperDeskCard>
            <CardTitle
                title="You've already been invited"
                sub={
                    <span>
                        <b className="text-primary">{org}</b> invited{' '}
                        <span className="PaperDesk__mono">{signupPanelEmail.email}</span> to join them on PostHog. The
                        invite link is in your inbox.
                    </span>
                }
                className="mb-5"
            />
            {pendingInviteResent ? (
                <div className="flex gap-2 items-start py-2.5 px-3 text-sm text-primary text-left bg-success-highlight border border-success rounded">
                    <span className="font-bold text-success">✓</span>
                    <span>Sent. Look for an email from {org}. The link inside takes you straight in.</span>
                </div>
            ) : (
                <div className="flex flex-col gap-2.5">
                    <LemonButton
                        type="primary"
                        size="large"
                        center
                        fullWidth
                        data-attr="pending-invite-resend"
                        loading={isPendingInviteResending}
                        onClick={() => resendPendingInvite(signupPanelEmail.email)}
                    >
                        Resend invite email
                    </LemonButton>
                    <LemonButton
                        size="large"
                        center
                        fullWidth
                        data-attr="pending-invite-create-own-org"
                        onClick={() => dismissPendingInvite()}
                    >
                        I'd rather create my own organization
                    </LemonButton>
                </div>
            )}
        </PaperDeskCard>
    )
}

/** Step 2 — passkey or password. */
function SignupAuthPanel(): JSX.Element {
    const {
        signupPanelEmail,
        isSignupPanelAuthSubmitting,
        validatedPassword,
        passkeySignupEnabled,
        passkeyRegistered,
        isPasskeyRegistering,
        passkeyError,
    } = useValues(signupLogic)
    const { registerPasskey, setPanel } = useActions(signupLogic)

    const footer = (
        <>
            <p className="PaperDesk__terms mt-5 mb-0 text-xs leading-relaxed text-tertiary text-center">
                By creating an account, you agree to our{' '}
                <Link to="https://posthog.com/terms" target="_blank">
                    Terms of Service ↗
                </Link>{' '}
                and{' '}
                <Link to="https://posthog.com/privacy" target="_blank">
                    Privacy Policy ↗
                </Link>
                .
            </p>
            <p className="mt-3 mb-0 text-sm text-secondary text-center">
                <Link
                    onClick={() => setPanel(0)}
                    className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                >
                    ← Use a different email
                </Link>
            </p>
        </>
    )

    return (
        <PaperDeskCard footer={footer}>
            <CardTitle
                title="Secure your account"
                sub={
                    <span>
                        Signing up as <span className="PaperDesk__mono">{signupPanelEmail.email}</span>
                    </span>
                }
            />
            {passkeyError && (
                <div className="mb-4 py-2.5 px-3 text-sm leading-normal text-primary text-left bg-danger-highlight border border-danger rounded">
                    {passkeyError}
                </div>
            )}
            {passkeySignupEnabled &&
                (passkeyRegistered ? (
                    <div className="PaperDesk__note text-center py-3 px-3.5 text-xs leading-relaxed text-secondary bg-[#fbfbf9] border border-dashed border-[#c5c6bd] rounded">
                        Passkey registered. Continue below.
                    </div>
                ) : (
                    <LemonButton
                        type="secondary"
                        size="large"
                        fullWidth
                        icon={<img src={passkeyLogo} alt="Passkey" className="object-contain w-7 h-7" />}
                        onClick={registerPasskey}
                        loading={isPasskeyRegistering}
                        disabled={isPasskeyRegistering}
                        data-attr="signup-passkey"
                        center
                    >
                        Sign up with a passkey
                    </LemonButton>
                ))}
            {!passkeyRegistered && (
                <div className="my-4 flex gap-3 items-center">
                    <span className="flex-1 h-px bg-[#e0e1d9]" />
                    <span className="text-xs text-secondary whitespace-nowrap">or use a password</span>
                    <span className="flex-1 h-px bg-[#e0e1d9]" />
                </div>
            )}
            <Form logic={signupLogic} formKey="signupPanelAuth" enableFormOnSubmit className="flex flex-col gap-4">
                {!passkeyRegistered && (
                    <LemonField
                        name="password"
                        label={
                            <div className="flex items-baseline justify-between w-full">
                                <span>Password</span>
                                <PasswordStrength validatedPassword={validatedPassword} />
                            </div>
                        }
                    >
                        {({ value, onChange, error, id }) => (
                            <LemonInput
                                id={id}
                                className="ph-ignore-input"
                                data-attr="password"
                                type="password"
                                autoFocus
                                autoComplete="new-password"
                                placeholder="••••••••••"
                                value={value ?? ''}
                                onChange={onChange}
                                status={error ? 'danger' : 'default'}
                                fullWidth
                            />
                        )}
                    </LemonField>
                )}
                <LemonButton
                    type="primary"
                    size="large"
                    center
                    fullWidth
                    htmlType="submit"
                    data-attr="signup-auth-continue"
                    loading={isSignupPanelAuthSubmitting}
                    disabledReason={
                        !passkeyRegistered && validatedPassword.feedback ? validatedPassword.feedback : undefined
                    }
                >
                    Create account
                </LemonButton>
            </Form>
        </PaperDeskCard>
    )
}

/** Step 3 — profile (name, organization, role, referral), like the legacy onboarding. */
function SignupProfilePanel(): JSX.Element {
    const {
        isSignupPanelOnboardingSubmitting,
        signupPanelOnboardingManualErrors,
        challengeRequired,
        turnstileSiteKey,
        turnstileToken,
        signupPanelEmail,
    } = useValues(signupLogic)
    const { preflight } = useValues(preflightLogic)
    const { setTurnstileToken, setPanel } = useActions(signupLogic)

    const submitLabel = !preflight?.demo
        ? 'Create account'
        : !isSignupPanelOnboardingSubmitting
          ? 'Enter the demo environment'
          : 'Preparing demo data…'

    const footer = (
        <>
            <p className="PaperDesk__terms mt-5 mb-0 text-xs leading-relaxed text-tertiary text-center">
                By {preflight?.demo ? 'entering the demo environment' : 'creating an account'}, you agree to our{' '}
                <Link to="https://posthog.com/terms" target="_blank">
                    Terms of Service ↗
                </Link>{' '}
                and{' '}
                <Link to="https://posthog.com/privacy" target="_blank">
                    Privacy Policy ↗
                </Link>
                .
            </p>
            {!preflight?.demo && (
                <p className="mt-5 mb-0 text-sm text-secondary text-center">
                    <Link
                        onClick={() => setPanel(1)}
                        className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                    >
                        ← or go back
                    </Link>
                </p>
            )}
        </>
    )

    return (
        <PaperDeskCard footer={footer}>
            <CardTitle
                title="Tell us about yourself"
                sub={
                    <span>
                        Setting up the account for <span className="PaperDesk__mono">{signupPanelEmail.email}</span>
                    </span>
                }
            />
            {signupPanelOnboardingManualErrors?.generic && (
                <div className="mb-4 py-2.5 px-3 text-sm leading-normal text-primary text-left bg-danger-highlight border border-danger rounded">
                    {signupPanelOnboardingManualErrors.generic.detail || 'Could not complete your signup.'}
                </div>
            )}
            <Form
                logic={signupLogic}
                formKey="signupPanelOnboarding"
                enableFormOnSubmit
                className="flex flex-col gap-4"
            >
                <LemonField name="name" label="Your name">
                    {({ value, onChange, error, id }) => (
                        <LemonInput
                            id={id}
                            className="ph-ignore-input"
                            data-attr="signup-name"
                            autoFocus
                            placeholder="Jane Doe"
                            autoComplete="name"
                            value={value ?? ''}
                            onChange={onChange}
                            status={error ? 'danger' : 'default'}
                            fullWidth
                        />
                    )}
                </LemonField>
                <LemonField name="organization_name" label="Organization name">
                    {({ value, onChange, error, id }) => (
                        <LemonInput
                            id={id}
                            className="ph-ignore-input"
                            data-attr="signup-organization-name"
                            placeholder="Hogflix Movies"
                            value={value ?? ''}
                            onChange={onChange}
                            status={error ? 'danger' : 'default'}
                            fullWidth
                        />
                    )}
                </LemonField>
                <SignupRoleSelect />
                <SignupReferralSource disabled={isSignupPanelOnboardingSubmitting} />
                {challengeRequired && turnstileSiteKey ? (
                    <TurnstileChallenge
                        siteKey={turnstileSiteKey}
                        onSuccess={setTurnstileToken}
                        tokenReceived={!!turnstileToken}
                        email={signupPanelEmail.email}
                    />
                ) : (
                    <LemonButton
                        type="primary"
                        size="large"
                        center
                        fullWidth
                        htmlType="submit"
                        data-attr="signup-submit"
                        loading={isSignupPanelOnboardingSubmitting}
                    >
                        {submitLabel}
                    </LemonButton>
                )}
            </Form>
        </PaperDeskCard>
    )
}

function Signup(): JSX.Element | null {
    const { user } = useValues(userLogic)
    const { panel } = useValues(signupLogic)

    if (user) {
        return null
    }

    return (
        <PaperDeskScene notes={NOTES[panel] ?? NOTES[0]}>
            {panel === 0 ? <SignupEmailPanel /> : panel === 1 ? <SignupAuthPanel /> : <SignupProfilePanel />}
        </PaperDeskScene>
    )
}

export { Signup as PaperDeskSignup }
