import { useActions, useValues } from 'kea'
import { Form, Field as FormField } from 'kea-forms'
import { type ChangeEvent, useEffect } from 'react'

import { Logomark } from 'lib/brand/Logomark'
import { JudgeHog } from 'lib/components/hedgehogs'
import SignupRoleSelect from 'lib/components/SignupRoleSelect'
import { SSOEnforcedLoginButton } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { loginLogic } from 'scenes/authentication/login/loginLogic'
import {
    OrgTile,
    PaperCardTitle,
    PaperDivider,
    PaperField,
    PaperFooterNote,
    PaperInput,
    PaperLink,
    PaperLockedEmail,
    PaperPasswordStrength,
    PaperPrimaryButton,
    PaperSecondaryButton,
    PaperSocialIcons,
} from 'scenes/authentication/shared/paperDesk/PaperDeskControls'
import { PaperDeskCard, PaperDeskScene } from 'scenes/authentication/shared/paperDesk/PaperDeskScene'
import { TurnstileChallenge } from 'scenes/authentication/signup/signupForm/TurnstileChallenge'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { PrevalidatedInvite } from '~/types'

import { inviteSignupLogic } from '../../inviteSignupLogic'

function InviteNewUser({ invite }: { invite: PrevalidatedInvite }): JSX.Element {
    const {
        isSignupSubmitting,
        signup,
        signupManualErrors,
        passkeyRegistered,
        isPasskeyRegistering,
        passkeyError,
        passkeySignupEnabled,
        challengeRequired,
        turnstileSiteKey,
        turnstileToken,
    } = useValues(inviteSignupLogic)
    const { registerPasskey, setTurnstileToken } = useActions(inviteSignupLogic)
    const { precheck } = useActions(loginLogic)
    const { precheckResponse, precheckResponseLoading } = useValues(loginLogic)
    const { openSupportForm } = useActions(supportLogic)
    const org = invite.organization_name
    const extraFieldsHidden = !!precheckResponse.sso_enforcement

    useEffect(() => {
        precheck({ email: invite.target_email })
    }, [invite.target_email]) // oxlint-disable-line react-hooks/exhaustive-deps

    const inviteHeader = (
        <div className="PaperDesk__inviteHeader">
            <div className="PaperDesk__inviteHeader-row">
                <OrgTile name={org} />
                <span className="PaperDesk__inviteHeader-mark">
                    <Logomark />
                </span>
            </div>
            <div className="text-center">
                <p className="PaperDesk__inviteHeader-meta">You've been invited to join</p>
                <p className="PaperDesk__inviteHeader-org">{org}</p>
                <p className="PaperDesk__inviteHeader-meta mt-1.5">on PostHog</p>
            </div>
        </div>
    )

    const footer = (
        <>
            <p className="PaperDesk__terms">
                By continuing you agree to our{' '}
                <Link to="https://posthog.com/terms" target="_blank">
                    terms
                </Link>{' '}
                and{' '}
                <Link to="https://posthog.com/privacy" target="_blank">
                    privacy policy
                </Link>
                .
            </p>
            <PaperFooterNote>
                Already have an account? <PaperLink to={urls.login()}>Log in →</PaperLink>
            </PaperFooterNote>
        </>
    )

    return (
        <PaperDeskScene notes={["// you've been invited", `// ${org.toLowerCase()} is waiting`]}>
            <PaperDeskCard top={inviteHeader} footer={footer}>
                <PaperCardTitle title="Create your account" sub="Your teammates are already in. This takes a minute." />
                {signupManualErrors?.generic && (
                    <div className="PaperDesk__error mb-4">
                        {signupManualErrors.generic.detail || 'Could not complete your signup.'}{' '}
                        <PaperLink onClick={() => openSupportForm({ kind: 'support', target_area: 'login' })}>
                            Need help?
                        </PaperLink>
                    </div>
                )}
                {passkeyError && <div className="PaperDesk__error mb-4">{passkeyError}</div>}
                <Form
                    logic={inviteSignupLogic}
                    formKey="signup"
                    enableFormOnSubmit
                    className="flex flex-col gap-[18px]"
                >
                    <PaperField label="Email" help="The invite is tied to this address.">
                        <PaperLockedEmail email={invite.target_email} />
                    </PaperField>

                    {!extraFieldsHidden && (
                        <>
                            {passkeySignupEnabled && !passkeyRegistered && (
                                <PaperSecondaryButton
                                    onClick={registerPasskey}
                                    disabled={isPasskeyRegistering}
                                    data-attr="invite-signup-passkey"
                                >
                                    Sign up with a passkey
                                </PaperSecondaryButton>
                            )}
                            {!passkeyRegistered && (
                                <FormField name="password">
                                    {({ value, onChange, error, id }) => (
                                        <PaperField
                                            label="Password"
                                            helpError={!!error}
                                            help={error}
                                            right={<PaperPasswordStrength password={signup.password ?? ''} />}
                                        >
                                            <PaperInput
                                                id={id}
                                                type="password"
                                                autoComplete="new-password"
                                                placeholder="••••••••••"
                                                value={value ?? ''}
                                                onChange={(e: ChangeEvent<HTMLInputElement>) =>
                                                    onChange(e.target.value)
                                                }
                                                invalid={!!error}
                                            />
                                        </PaperField>
                                    )}
                                </FormField>
                            )}
                            <FormField name="first_name">
                                {({ value, onChange, error, id }) => (
                                    <PaperField label="Your name" helpError={!!error} help={error}>
                                        <PaperInput
                                            id={id}
                                            placeholder="Jane Doe"
                                            autoComplete="name"
                                            value={value ?? ''}
                                            onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
                                            invalid={!!error}
                                        />
                                    </PaperField>
                                )}
                            </FormField>
                            <SignupRoleSelect />
                        </>
                    )}

                    {!precheckResponse.sso_enforcement &&
                        (challengeRequired && turnstileSiteKey ? (
                            <TurnstileChallenge
                                siteKey={turnstileSiteKey}
                                onSuccess={setTurnstileToken}
                                tokenReceived={!!turnstileToken}
                                email={invite.target_email}
                            />
                        ) : (
                            <PaperPrimaryButton
                                loading={isSignupSubmitting || precheckResponseLoading}
                                loadingLabel="Joining…"
                            >
                                Join {org}
                            </PaperPrimaryButton>
                        ))}
                    {precheckResponse.sso_enforcement && (
                        <SSOEnforcedLoginButton
                            provider={precheckResponse.sso_enforcement}
                            email={invite.target_email}
                            actionText="Continue"
                            extraQueryParams={{ invite_id: invite.id }}
                        />
                    )}
                    {precheckResponse.saml_available && !precheckResponse.sso_enforcement && (
                        <SSOEnforcedLoginButton
                            provider="saml"
                            email={invite.target_email}
                            actionText="Continue"
                            extraQueryParams={{ invite_id: invite.id }}
                        />
                    )}
                </Form>
                {!extraFieldsHidden && (
                    <>
                        <PaperDivider label="or continue with" />
                        <PaperSocialIcons
                            verb="Continue"
                            caption="Use the same email the invite was sent to."
                            extraQueryParams={{ invite_id: invite.id }}
                        />
                    </>
                )}
            </PaperDeskCard>
        </PaperDeskScene>
    )
}

function InviteExistingAccount({ invite }: { invite: PrevalidatedInvite }): JSX.Element {
    const { user } = useValues(userLogic)
    const { acceptInvite } = useActions(inviteSignupLogic)
    const { acceptedInvite, acceptedInviteLoading } = useValues(inviteSignupLogic)
    const org = invite.organization_name

    return (
        <PaperDeskScene notes={['// hey, welcome back', '// one more org for you']}>
            <PaperDeskCard>
                <div className="mb-4 flex justify-center">
                    <OrgTile name={org} />
                </div>
                <PaperCardTitle
                    title={`Join ${org}`}
                    sub="You'll accept this invite with your existing PostHog account:"
                    className="mb-[18px]"
                />
                {user && (
                    <div className="PaperDesk__whoami mb-4">
                        <ProfilePicture user={user} size="xl" />
                        <div className="min-w-0">
                            <p className="PaperDesk__whoami-name">{user.first_name}</p>
                            <p className="PaperDesk__whoami-email">{user.email}</p>
                        </div>
                    </div>
                )}
                <p className="PaperDesk__sub mb-[18px] text-left">
                    Accepting adds <b className="text-primary">{org}</b> to your account. Switch between organizations
                    any time from the upper left of the app.
                </p>
                {acceptedInvite ? (
                    <PaperPrimaryButton
                        htmlType="button"
                        onClick={() => {
                            window.location.href = '/'
                        }}
                    >
                        Go to {org} →
                    </PaperPrimaryButton>
                ) : (
                    <div className="flex flex-col gap-2.5">
                        <PaperPrimaryButton htmlType="button" loading={acceptedInviteLoading} onClick={acceptInvite}>
                            Accept invite
                        </PaperPrimaryButton>
                        <PaperSecondaryButton
                            onClick={() => {
                                window.location.href = '/'
                            }}
                        >
                            Not now, back to PostHog
                        </PaperSecondaryButton>
                    </div>
                )}
            </PaperDeskCard>
        </PaperDeskScene>
    )
}

function InviteInvalid(): JSX.Element {
    const { error } = useValues(inviteSignupLogic)
    const { openSupportForm } = useActions(supportLogic)

    const footer = (
        <PaperFooterNote>
            <PaperLink to={urls.login()}>Log in</PaperLink>
            <span className="mx-1.5 text-muted">·</span>
            <PaperLink to="https://posthog.com" target="_blank">
                posthog.com ↗
            </PaperLink>
        </PaperFooterNote>
    )

    return (
        <PaperDeskScene notes={['// hmm', "// this invite isn't right"]}>
            <PaperDeskCard footer={footer}>
                <div className="flex flex-col items-center text-center">
                    <JudgeHog className="PaperDesk__hog h-28" />
                    <h1 className="PaperDesk__title mt-3">This invite isn't valid</h1>
                    <p className="PaperDesk__sub mb-[18px]">
                        {error?.detail ||
                            'The court finds this link expired, already used, or sent to a different email address.'}
                    </p>
                    <p className="PaperDesk__note mb-[18px]">
                        Invites are personal links that work once. Ask whoever invited you to <b>send a fresh one</b>{' '}
                        from their organization's members settings. It takes them ten seconds.
                    </p>
                    <PaperSecondaryButton onClick={() => openSupportForm({ kind: 'bug', target_area: 'login' })}>
                        Contact support
                    </PaperSecondaryButton>
                </div>
            </PaperDeskCard>
        </PaperDeskScene>
    )
}

function InviteSignup(): JSX.Element {
    const { invite, inviteLoading, error } = useValues(inviteSignupLogic)
    const { user } = useValues(userLogic)

    if (inviteLoading) {
        return <SpinnerOverlay sceneLevel />
    }
    if (error) {
        return <InviteInvalid />
    }
    if (invite) {
        return user ? <InviteExistingAccount invite={invite} /> : <InviteNewUser invite={invite} />
    }
    return <SpinnerOverlay sceneLevel />
}

export { InviteSignup as PaperDeskInviteSignup }
