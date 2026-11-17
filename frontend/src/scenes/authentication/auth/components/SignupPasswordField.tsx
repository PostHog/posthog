import { useActions, useValues } from 'kea'

import PasswordStrength from 'lib/components/PasswordStrength'
import passkeyLogo from 'lib/components/SocialLoginButton/passkey.svg'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'

import { signupLogic } from '../signupLogic'
import { SignupPasswordStrength } from './SignupPasswordStrength'

export function SignupPasswordField(): JSX.Element {
    const {
        signupPanelAuth,
        signupPanelAuthErrors,
        validatedPassword,
        passwordEstimatorReadyLoading,
        featureFlags,
        passkeyRegistered,
        isPasskeyRegistering,
        passkeyError,
    } = useValues(signupLogic)
    const { setSignupPanelAuthValue, registerPasskey } = useActions(signupLogic)
    const showCrackEstimate = featureFlags[FEATURE_FLAGS.SIGNUP_PASSWORD_CRACK_ESTIMATED] === 'test'

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
                                {!showCrackEstimate && <PasswordStrength validatedPassword={validatedPassword} />}
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
                            aria-describedby={showCrackEstimate ? 'signup-password-strength' : undefined}
                            value={signupPanelAuth.password}
                            onChange={(value) => setSignupPanelAuthValue('password', value)}
                            status={signupPanelAuthErrors.password ? 'danger' : 'default'}
                            fullWidth
                        />
                    </LemonField.Pure>
                    {showCrackEstimate && (
                        <SignupPasswordStrength
                            password={signupPanelAuth.password}
                            validatedPassword={validatedPassword}
                            estimatorLoading={passwordEstimatorReadyLoading}
                        />
                    )}
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
