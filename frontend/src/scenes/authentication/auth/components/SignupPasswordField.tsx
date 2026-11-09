import { useActions, useValues } from 'kea'

import PasswordStrength from 'lib/components/PasswordStrength'
import passkeyLogo from 'lib/components/SocialLoginButton/passkey.svg'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'

import { signupLogic } from '../signupLogic'

export function SignupPasswordField(): JSX.Element {
    const {
        signupPanelAuth,
        signupPanelAuthErrors,
        validatedPassword,
        passkeyRegistered,
        isPasskeyRegistering,
        passkeyError,
    } = useValues(signupLogic)
    const { setSignupPanelAuthValue, registerPasskey } = useActions(signupLogic)

    return (
        <div className="flex flex-col gap-2 pt-4">
            {passkeyError && <AuthBanner variant="danger">{passkeyError}</AuthBanner>}
            {passkeyRegistered ? (
                <AuthBanner variant="success">Passkey registered. Continue below.</AuthBanner>
            ) : (
                <>
                    <LemonField.Pure
                        htmlFor="auth-signup-password"
                        label={
                            <div className="flex items-baseline justify-between w-full">
                                <span>Choose a password</span>
                                <PasswordStrength validatedPassword={validatedPassword} />
                            </div>
                        }
                        error={signupPanelAuthErrors.password}
                    >
                        <LemonInput
                            id="auth-signup-password"
                            className="ph-ignore-input"
                            data-attr="password"
                            type="password"
                            autoFocus
                            autoComplete="new-password"
                            value={signupPanelAuth.password}
                            onChange={(value) => setSignupPanelAuthValue('password', value)}
                            status={signupPanelAuthErrors.password ? 'danger' : 'default'}
                            fullWidth
                        />
                    </LemonField.Pure>
                    <LemonButton
                        type="tertiary"
                        size="small"
                        icon={<img src={passkeyLogo} alt="" className="object-contain w-5 h-5" />}
                        onClick={registerPasskey}
                        loading={isPasskeyRegistering}
                        data-attr="signup-passkey"
                        className="self-start"
                    >
                        Use a passkey instead
                    </LemonButton>
                </>
            )}
        </div>
    )
}
