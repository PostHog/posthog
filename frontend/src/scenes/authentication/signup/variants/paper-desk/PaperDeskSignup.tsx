import { useActions, useValues } from 'kea'
import { Form, Field as FormField } from 'kea-forms'
import { type ChangeEvent, useState } from 'react'

import { getCookie } from 'lib/api'
import SignupReferralSource from 'lib/components/SignupReferralSource'
import SignupRoleSelect from 'lib/components/SignupRoleSelect'
import { Link } from 'lib/lemon-ui/Link'
import {
    KeyIcon,
    PaperCardTitle,
    PaperDivider,
    PaperField,
    PaperFooterNote,
    PaperInput,
    PaperLink,
    PaperPasswordStrength,
    PaperPrimaryButton,
    PaperRegionField,
    PaperSecondaryButton,
    PaperSocialIcons,
} from 'scenes/authentication/shared/paperDesk/PaperDeskControls'
import { PaperDeskCard, PaperDeskScene } from 'scenes/authentication/shared/paperDesk/PaperDeskScene'
import { TurnstileChallenge } from 'scenes/authentication/signup/signupForm/TurnstileChallenge'
import { userLogic } from 'scenes/userLogic'

import { signupLogic } from '../../signupForm/signupLogic'

const NOTES: Record<number, string[]> = {
    0: ['// create an account', '// 1M events free, every month'],
    1: ['// secure your account', '// make it a good one'],
    2: ['// almost there', '// last step'],
}

/** Step 1 — email (+ region, social, pending-invite branch). */
function SignupEmailPanel(): JSX.Element {
    const { isSignupPanelEmailSubmitting, signupPanelEmailManualErrors, pendingInvite, loginUrl } =
        useValues(signupLogic)
    const [showJoinOrg, setShowJoinOrg] = useState(false)
    const lastLoginMethod = getCookie('ph_last_login_method')
    const accountExists = !!signupPanelEmailManualErrors?.email

    if (pendingInvite) {
        return <PendingInvitePanel />
    }

    const footer = (
        <PaperFooterNote>
            Already have an account? <PaperLink to={loginUrl}>Log in →</PaperLink>
        </PaperFooterNote>
    )

    return (
        <PaperDeskCard footer={footer}>
            <PaperCardTitle title="Get started" sub="No credit card. No sales call. Just hogs." />
            <Form
                logic={signupLogic}
                formKey="signupPanelEmail"
                enableFormOnSubmit
                className="flex flex-col gap-[18px]"
            >
                <PaperRegionField />
                <FormField name="email">
                    {({ value, onChange, error, id }) => (
                        <PaperField
                            label="Email"
                            helpError={!!error}
                            help={
                                accountExists ? (
                                    <span>
                                        {error} <PaperLink to={loginUrl}>Log in instead →</PaperLink>
                                    </span>
                                ) : (
                                    error
                                )
                            }
                        >
                            <PaperInput
                                id={id}
                                type="email"
                                autoFocus
                                autoComplete="email"
                                placeholder="you@yourcompany.com"
                                value={value ?? ''}
                                onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
                                invalid={!!error}
                            />
                        </PaperField>
                    )}
                </FormField>
                <PaperPrimaryButton loading={isSignupPanelEmailSubmitting} loadingLabel="Checking…">
                    Continue
                </PaperPrimaryButton>
            </Form>
            <PaperDivider label="or sign up with" />
            <PaperSocialIcons verb="Sign up" lastUsed={lastLoginMethod} />
            <div className="mt-4 text-center">
                <button
                    type="button"
                    className="PaperDesk__link PaperDesk__link--muted text-[12.5px]"
                    onClick={() => setShowJoinOrg((v) => !v)}
                >
                    Trying to join an existing organization?
                </button>
                {showJoinOrg && (
                    <p className="PaperDesk__note mt-3">
                        You'll need your invite link. When a teammate invites you, we email you a personal link — that's
                        the only way in to their organization. Didn't get one? Check spam, or ask them to resend it from
                        their members settings.
                    </p>
                )}
            </div>
        </PaperDeskCard>
    )
}

function PendingInvitePanel(): JSX.Element {
    const { signupPanelEmail, pendingInvite, pendingInviteResent, isPendingInviteResending } = useValues(signupLogic)
    const { resendPendingInvite, dismissPendingInvite } = useActions(signupLogic)
    const org = pendingInvite?.organization_name ?? 'your team'

    return (
        <PaperDeskCard>
            <PaperCardTitle
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
                <div className="PaperDesk__success">
                    <span className="PaperDesk__success-check">✓</span>
                    <span>Sent. Look for an email from {org} — the link inside takes you straight in.</span>
                </div>
            ) : (
                <div className="flex flex-col gap-2.5">
                    <PaperPrimaryButton
                        htmlType="button"
                        loading={isPendingInviteResending}
                        loadingLabel="Resending…"
                        onClick={() => resendPendingInvite(signupPanelEmail.email)}
                    >
                        Resend invite email
                    </PaperPrimaryButton>
                    <PaperSecondaryButton onClick={() => dismissPendingInvite()}>
                        I'd rather create my own organization
                    </PaperSecondaryButton>
                </div>
            )}
        </PaperDeskCard>
    )
}

/** Step 2 — passkey or password. */
function SignupAuthPanel(): JSX.Element {
    const {
        signupPanelEmail,
        signupPanelAuth,
        isSignupPanelAuthSubmitting,
        validatedPassword,
        passkeySignupEnabled,
        passkeyRegistered,
        isPasskeyRegistering,
        passkeyError,
    } = useValues(signupLogic)
    const { registerPasskey, setPanel } = useActions(signupLogic)

    const footer = (
        <PaperFooterNote>
            <PaperLink onClick={() => setPanel(0)}>← Use a different email</PaperLink>
        </PaperFooterNote>
    )

    return (
        <PaperDeskCard footer={footer}>
            <PaperCardTitle
                title="Secure your account"
                sub={
                    <span>
                        Signing up as <span className="PaperDesk__mono">{signupPanelEmail.email}</span>
                    </span>
                }
            />
            {passkeyError && <div className="PaperDesk__error mb-4">{passkeyError}</div>}
            {passkeySignupEnabled &&
                (passkeyRegistered ? (
                    <div className="PaperDesk__note text-center">Passkey registered. Continue below.</div>
                ) : (
                    <PaperSecondaryButton
                        icon={
                            <span className="PaperDesk__sso-icon">
                                <KeyIcon size={17} />
                            </span>
                        }
                        onClick={registerPasskey}
                        disabled={isPasskeyRegistering}
                    >
                        Sign up with a passkey
                    </PaperSecondaryButton>
                ))}
            {!passkeyRegistered && <PaperDivider label="or use a password" />}
            <Form logic={signupLogic} formKey="signupPanelAuth" enableFormOnSubmit className="flex flex-col gap-[18px]">
                {!passkeyRegistered && (
                    <FormField name="password">
                        {({ value, onChange, error, id }) => (
                            <PaperField
                                label="Password"
                                helpError={!!error}
                                help={error}
                                right={<PaperPasswordStrength password={signupPanelAuth.password} />}
                            >
                                <PaperInput
                                    id={id}
                                    type="password"
                                    autoFocus
                                    autoComplete="new-password"
                                    placeholder="••••••••••"
                                    value={value ?? ''}
                                    onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
                                    invalid={!!error}
                                />
                            </PaperField>
                        )}
                    </FormField>
                )}
                <PaperPrimaryButton
                    loading={isSignupPanelAuthSubmitting}
                    disabled={!passkeyRegistered && !!validatedPassword.feedback}
                >
                    Continue
                </PaperPrimaryButton>
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
    const { setTurnstileToken, setPanel } = useActions(signupLogic)

    const footer = (
        <>
            <p className="PaperDesk__terms">
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
            <PaperFooterNote>
                <PaperLink onClick={() => setPanel(1)}>← or go back</PaperLink>
            </PaperFooterNote>
        </>
    )

    return (
        <PaperDeskCard footer={footer}>
            <PaperCardTitle
                title="Tell us about yourself"
                sub={
                    <span>
                        Setting up the account for <span className="PaperDesk__mono">{signupPanelEmail.email}</span>
                    </span>
                }
            />
            {signupPanelOnboardingManualErrors?.generic && (
                <div className="PaperDesk__error mb-4">
                    {signupPanelOnboardingManualErrors.generic.detail || 'Could not complete your signup.'}
                </div>
            )}
            <Form
                logic={signupLogic}
                formKey="signupPanelOnboarding"
                enableFormOnSubmit
                className="flex flex-col gap-[18px]"
            >
                <FormField name="name">
                    {({ value, onChange, error, id }) => (
                        <PaperField label="Your name" helpError={!!error} help={error}>
                            <PaperInput
                                id={id}
                                autoFocus
                                placeholder="Jane Doe"
                                autoComplete="name"
                                value={value ?? ''}
                                onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
                                invalid={!!error}
                            />
                        </PaperField>
                    )}
                </FormField>
                <FormField name="organization_name">
                    {({ value, onChange, error, id }) => (
                        <PaperField label="Organization name" helpError={!!error} help={error}>
                            <PaperInput
                                id={id}
                                placeholder="Hogflix Movies"
                                value={value ?? ''}
                                onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
                                invalid={!!error}
                            />
                        </PaperField>
                    )}
                </FormField>
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
                    <PaperPrimaryButton loading={isSignupPanelOnboardingSubmitting} loadingLabel="Creating account…">
                        Create account
                    </PaperPrimaryButton>
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
