import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import PasswordStrength from 'lib/components/PasswordStrength'
import passkeyLogo from 'lib/components/SocialLoginButton/passkey.svg'
import { SocialLoginButtons } from 'lib/components/SocialLoginButton/SocialLoginButton'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { pendingOAuthConnectionLogic } from 'scenes/authentication/shared/pendingOAuthConnectionLogic'

import { ConnectTitle } from '../components/ConnectTitle'
import { OtherRegionNotice } from '../components/OtherRegionNotice'
import { UseDifferentEmailLink } from '../components/UseDifferentEmailLink'
import { signupLogic } from '../signupLogic'

export function SignupCredentialsStep(): JSX.Element {
    const {
        signupEmail,
        isSignupPanelAuthSubmitting,
        validatedPassword,
        passkeyRegistered,
        isPasskeyRegistering,
        passkeyError,
    } = useValues(signupLogic)
    const { registerPasskey } = useActions(signupLogic)
    const { pendingConnection } = useValues(pendingOAuthConnectionLogic)

    const footer = (
        <>
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
            <UseDifferentEmailLink />
        </>
    )

    const greeting = (
        <>
            <span>Nice to meet you,</span> <span className="AuthScene__mono">{signupEmail}</span>
            <span>.</span>
        </>
    )

    return (
        <AuthSceneCard footer={footer}>
            <AuthCardTitle
                title={
                    pendingConnection ? (
                        <ConnectTitle lead="Create your account to connect" clientName={pendingConnection.clientName} />
                    ) : (
                        'Create your account'
                    )
                }
                sub={greeting}
            />
            {passkeyError && (
                <AuthBanner variant="danger" className="mb-4">
                    {passkeyError}
                </AuthBanner>
            )}
            {passkeyRegistered ? (
                <AuthBanner variant="success">Passkey registered. Continue below.</AuthBanner>
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
            )}
            {!passkeyRegistered && (
                <div className="my-4 flex gap-3 items-center">
                    <span className="flex-1 h-px bg-[#e0e1d9]" />
                    <span className="text-xs text-secondary whitespace-nowrap">or use a password</span>
                    <span className="flex-1 h-px bg-[#e0e1d9]" />
                </div>
            )}
            <Form logic={signupLogic} formKey="signupPanelAuth" enableFormOnSubmit className="flex flex-col gap-4">
                {/* Password managers save the new password under this username */}
                <input type="email" name="email" autoComplete="username" value={signupEmail} readOnly hidden />
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
                <OtherRegionNotice email={signupEmail} reason="no_account" />
            </Form>
            {/* A verified company domain with auto-join adds people who sign in with Google, GitHub or
                GitLab to their team's organization. An email signup creates a new organization instead. */}
            <SocialLoginButtons topDivider caption="or sign up with" captionLocation="top" />
        </AuthSceneCard>
    )
}
