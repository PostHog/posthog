import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import PasswordStrength from 'lib/components/PasswordStrength'
import passkeyLogo from 'lib/components/SocialLoginButton/passkey.svg'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { pendingOAuthConnectionLogic, reviewAccessCopy } from 'scenes/authentication/shared/pendingOAuthConnectionLogic'
import { signupLogic } from 'scenes/authentication/signup/signupForm/signupLogic'

import { HighlightedName } from '../components/HighlightedName'
import { NoAccountInRegionBanner } from '../components/NoAccountInRegionBanner'
import { UseDifferentEmailLink } from '../components/UseDifferentEmailLink'

export function SignupCredentialsStep(): JSX.Element {
    const {
        signupPanelEmail,
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

    const signingUpAs = (
        <>
            <span>Signing up as</span> <span className="AuthScene__mono">{signupPanelEmail.email}</span>
        </>
    )

    return (
        <AuthSceneCard footer={footer}>
            <AuthCardTitle
                title={
                    pendingConnection ? (
                        <>
                            <span>Create your account to connect </span>
                            <HighlightedName>{pendingConnection.clientName}</HighlightedName>
                        </>
                    ) : (
                        'Create your account'
                    )
                }
                sub={
                    pendingConnection ? (
                        <>
                            <span className="block">{signingUpAs}</span>
                            <span className="block mt-1">
                                {reviewAccessCopy(pendingConnection, 'Once your account is ready')}
                            </span>
                        </>
                    ) : (
                        signingUpAs
                    )
                }
            />
            <NoAccountInRegionBanner email={signupPanelEmail.email} />
            {passkeyError && (
                <div className="mb-4 py-2.5 px-3 text-sm leading-normal text-primary text-left bg-danger-highlight border border-danger rounded">
                    <span>{passkeyError}</span>
                </div>
            )}
            {passkeyRegistered ? (
                <div className="AuthScene__note text-center py-3 px-3.5 text-xs leading-relaxed text-secondary border border-dashed rounded">
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
                <input
                    type="email"
                    name="email"
                    autoComplete="username"
                    value={signupPanelEmail.email}
                    readOnly
                    hidden
                />
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
        </AuthSceneCard>
    )
}
