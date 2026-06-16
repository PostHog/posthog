import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect } from 'react'

import { Logomark } from 'lib/brand/Logomark'
import { JudgeHog } from 'lib/components/hedgehogs'
import PasswordStrength from 'lib/components/PasswordStrength'
import SignupRoleSelect from 'lib/components/SignupRoleSelect'
import { SocialLoginButtons, SSOEnforcedLoginButton } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { loginLogic } from 'scenes/authentication/login/loginLogic'
import { CardTitle } from 'scenes/authentication/shared/paperDesk/CardTitle'
import { OrgTile } from 'scenes/authentication/shared/paperDesk/OrgTile'
import { PaperDeskCard, PaperDeskScene } from 'scenes/authentication/shared/paperDesk/PaperDeskScene'
import { TurnstileChallenge } from 'scenes/authentication/signup/signupForm/TurnstileChallenge'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { PrevalidatedInvite } from '~/types'

import { inviteSignupLogic } from '../../inviteSignupLogic'

function InviteNewUser({ invite }: { invite: PrevalidatedInvite }): JSX.Element {
    const {
        isSignupSubmitting,
        signupManualErrors,
        validatedPassword,
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
        <div className="flex flex-col gap-3 items-center mb-5">
            <div className="flex gap-3 items-center">
                <OrgTile name={org} />
                <span className="PaperDesk__inviteHeader-mark inline-flex opacity-90">
                    <Logomark />
                </span>
            </div>
            <div className="text-center">
                <p className="m-0 text-sm text-secondary">You've been invited to join</p>
                <p className="pb-1.5 mt-0.5 mb-0 font-title text-3xl font-extrabold text-primary tracking-tight border-b border-dashed border-[#c5c6bd]">
                    {org}
                </p>
                <p className="m-0 mt-1.5 text-sm text-secondary">on PostHog</p>
            </div>
        </div>
    )

    const footer = (
        <>
            <p className="PaperDesk__terms mt-5 mb-0 text-xs leading-relaxed text-tertiary text-center">
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
            <p className="mt-5 mb-0 text-sm text-secondary text-center">
                Already have an account?{' '}
                <Link
                    to={urls.login()}
                    className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                >
                    Log in →
                </Link>
            </p>
        </>
    )

    return (
        <PaperDeskScene notes={["// you've been invited", `// ${org.toLowerCase()} is waiting`]}>
            <PaperDeskCard top={inviteHeader} footer={footer}>
                <CardTitle title="Create your account" sub="Your teammates are already in. This takes a minute." />
                {signupManualErrors?.generic && (
                    <div className="mb-4 py-2.5 px-3 text-sm leading-normal text-primary text-left bg-danger-highlight border border-danger rounded">
                        {signupManualErrors.generic.detail || 'Could not complete your signup.'}{' '}
                        <Link
                            onClick={() => openSupportForm({ kind: 'support', target_area: 'login' })}
                            className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
                        >
                            Need help?
                        </Link>
                    </div>
                )}
                {passkeyError && (
                    <div className="mb-4 py-2.5 px-3 text-sm leading-normal text-primary text-left bg-danger-highlight border border-danger rounded">
                        {passkeyError}
                    </div>
                )}
                <Form logic={inviteSignupLogic} formKey="signup" enableFormOnSubmit className="flex flex-col gap-4">
                    <LemonField.Pure label="Email" help="The invite is tied to this address.">
                        <LemonInput type="email" value={invite.target_email} disabled fullWidth />
                    </LemonField.Pure>

                    {!extraFieldsHidden && (
                        <>
                            {passkeySignupEnabled && !passkeyRegistered && (
                                <LemonButton
                                    fullWidth
                                    onClick={registerPasskey}
                                    disabled={isPasskeyRegistering}
                                    data-attr="invite-signup-passkey"
                                >
                                    Sign up with a passkey
                                </LemonButton>
                            )}
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
                                            type="password"
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
                            <LemonField name="first_name" label="Your name">
                                {({ value, onChange, error, id }) => (
                                    <LemonInput
                                        id={id}
                                        placeholder="Jane Doe"
                                        autoComplete="name"
                                        value={value ?? ''}
                                        onChange={onChange}
                                        status={error ? 'danger' : 'default'}
                                        fullWidth
                                    />
                                )}
                            </LemonField>
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
                            <LemonButton
                                type="primary"
                                fullWidth
                                htmlType="submit"
                                loading={isSignupSubmitting || precheckResponseLoading}
                            >
                                Join {org}
                            </LemonButton>
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
                    <SocialLoginButtons
                        topDivider
                        caption="or continue with"
                        captionLocation="top"
                        extraQueryParams={{ invite_id: invite.id }}
                    />
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
                <CardTitle
                    title={`Join ${org}`}
                    sub="You'll accept this invite with your existing PostHog account:"
                    className="mb-4"
                />
                {user && (
                    <div className="mb-4 flex gap-3 items-center py-2.5 px-3 border border-dashed border-[#c5c6bd] rounded-lg">
                        <ProfilePicture user={user} size="xl" />
                        <div className="min-w-0">
                            <p className="m-0 text-sm font-semibold text-primary">{user.first_name}</p>
                            <p className="m-0 overflow-hidden font-mono text-xs text-secondary text-ellipsis whitespace-nowrap">
                                {user.email}
                            </p>
                        </div>
                    </div>
                )}
                <p className="PaperDesk__sub mb-4 text-left text-sm text-secondary text-pretty">
                    Accepting adds <b className="text-primary">{org}</b> to your account. Switch between organizations
                    any time from the upper left of the app.
                </p>
                {acceptedInvite ? (
                    <LemonButton
                        type="primary"
                        fullWidth
                        onClick={() => {
                            window.location.href = '/'
                        }}
                    >
                        Go to {org} →
                    </LemonButton>
                ) : (
                    <div className="flex flex-col gap-2.5">
                        <LemonButton type="primary" fullWidth loading={acceptedInviteLoading} onClick={acceptInvite}>
                            Accept invite
                        </LemonButton>
                        <LemonButton
                            fullWidth
                            onClick={() => {
                                window.location.href = '/'
                            }}
                        >
                            Not now, back to PostHog
                        </LemonButton>
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
        <p className="mt-5 mb-0 text-sm text-secondary text-center">
            <Link
                to={urls.login()}
                className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
            >
                Log in
            </Link>
            <span className="mx-1.5 text-muted">·</span>
            <Link
                to="https://posthog.com"
                target="_blank"
                className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-warning"
            >
                posthog.com ↗
            </Link>
        </p>
    )

    return (
        <PaperDeskScene notes={['// hmm', "// this invite isn't right"]}>
            <PaperDeskCard footer={footer}>
                <div className="flex flex-col items-center text-center">
                    <JudgeHog className="block w-auto mx-auto h-28" />
                    <h1 className="m-0 mt-3 font-title text-2xl font-extrabold leading-tight text-primary text-center tracking-tight">
                        This invite isn't valid
                    </h1>
                    <p className="PaperDesk__sub mt-2 mb-4 text-sm text-secondary text-center text-pretty">
                        {error?.detail ||
                            'The court finds this link expired, already used, or sent to a different email address.'}
                    </p>
                    <p className="PaperDesk__note mb-4 py-3 px-3.5 text-xs leading-relaxed text-secondary text-left bg-[#fbfbf9] border border-dashed border-[#c5c6bd] rounded">
                        Invites are personal links that work once. Ask whoever invited you to <b>send a fresh one</b>{' '}
                        from their organization's members settings. It takes them ten seconds.
                    </p>
                    <LemonButton fullWidth onClick={() => openSupportForm({ kind: 'bug', target_area: 'login' })}>
                        Contact support
                    </LemonButton>
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
