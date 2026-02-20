import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonBanner, LemonButton, LemonInput } from '@posthog/lemon-ui'

import PasswordStrength from 'lib/components/PasswordStrength'
import passkeyLogo from 'lib/components/SocialLoginButton/passkey.svg'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { IconKey } from 'lib/lemon-ui/icons'

import { signupLogic } from '../signupLogic'

export function SignupPanelAuth(): JSX.Element | null {
    const { registerPasskey } = useActions(signupLogic)
    const {
        isSignupPanelAuthSubmitting,
        validatedPassword,
        signupPanelEmail,
        passkeyRegistered,
        isPasskeyRegistering,
        passkeyError,
        passkeySignupEnabled,
    } = useValues(signupLogic)

    return (
        <div className="deprecated-space-y-4 Signup__panel__auth">
            <div className="text-center mb-4">
                <p className="text-secondary mb-1">Signing up as</p>
                <p className="font-semibold text-lg">{signupPanelEmail.email}</p>
            </div>

            {passkeyError && (
                <LemonBanner type="error" className="mb-4">
                    {passkeyError}
                </LemonBanner>
            )}

            {passkeySignupEnabled && (
                <>
                    {passkeyRegistered ? (
                        <div className="border border-success-lighter rounded-lg p-4 bg-success-highlight text-center">
                            <img src={passkeyLogo} alt="Passkey" className="w-8 h-8 mx-auto mb-2" />
                            <p className="font-semibold text-success mb-1">Passkey registered successfully!</p>
                            <p className="text-secondary text-sm">
                                You can use this passkey to sign in to your account.
                            </p>
                        </div>
                    ) : (
                        <LemonButton
                            fullWidth
                            type="secondary"
                            center
                            size="large"
                            icon={<img src={passkeyLogo} alt="Passkey" className="object-contain w-7 h-7" />}
                            onClick={registerPasskey}
                            loading={isPasskeyRegistering}
                            disabled={isPasskeyRegistering}
                            data-attr="signup-passkey"
                        >
                            Sign up with passkey
                        </LemonButton>
                    )}

                    <div className="flex items-center gap-3 my-4">
                        <div className="flex-1 border-t border-border" />
                        <span className="text-secondary text-sm">or use a password</span>
                        <div className="flex-1 border-t border-border" />
                    </div>
                </>
            )}

            <Form logic={signupLogic} formKey="signupPanelAuth" className="deprecated-space-y-4" enableFormOnSubmit>
                <LemonField
                    name="password"
                    label={
                        <div className="flex flex-1 items-center justify-between">
                            <span className="flex items-center gap-1">
                                <IconKey className="text-muted" />
                                Password
                            </span>
                            <PasswordStrength validatedPassword={validatedPassword} />
                        </div>
                    }
                >
                    <LemonInput
                        type="password"
                        autoComplete="new-password"
                        className="ph-ignore-input"
                        data-attr="password"
                        placeholder="••••••••••"
                        disabled={isSignupPanelAuthSubmitting || passkeyRegistered}
                    />
                </LemonField>
                <LemonButton
                    fullWidth
                    type="primary"
                    status="alt"
                    center
                    htmlType="submit"
                    data-attr="signup-auth-continue"
                    loading={isSignupPanelAuthSubmitting}
                    disabled={isSignupPanelAuthSubmitting}
                    size="large"
                >
                    Continue
                </LemonButton>
            </Form>
        </div>
    )
}
