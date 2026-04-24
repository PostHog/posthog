import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import passkeyLogo from 'lib/components/SocialLoginButton/passkey.svg'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { login2FALogic } from './login2FALogic'

export function Login2FA(): JSX.Element {
    const { isTwofactortokenSubmitting, generalError, passkey2FALoading, passkeysAvailable, totpAvailable } =
        useValues(login2FALogic)
    const { beginPasskey2FA } = useActions(login2FALogic)
    const { preflight } = useValues(preflightLogic)

    return (
        <BridgePage
            view="login"
            hedgehog
            message={
                <>
                    Welcome to
                    <br /> PostHog{preflight?.cloud ? ' Cloud' : ''}!
                </>
            }
        >
            <div className="deprecated-space-y-2">
                <h2>Two-Factor Authentication</h2>
                <p>Enter a token from your authenticator app, use your passkey, or enter a backup code.</p>

                {passkeysAvailable && (
                    <>
                        <LemonButton
                            type="primary"
                            htmlType="button"
                            onClick={() => beginPasskey2FA()}
                            loading={passkey2FALoading}
                            fullWidth
                            center
                            size="large"
                            icon={<img src={passkeyLogo} alt="Passkey" className="object-contain w-6 h-6" />}
                        >
                            Use passkey
                        </LemonButton>
                        {totpAvailable && <LemonDivider className="my-4" label="Or" />}
                    </>
                )}

                {totpAvailable && (
                    <Form
                        logic={login2FALogic}
                        formKey="twofactortoken"
                        enableFormOnSubmit
                        className="deprecated-space-y-4"
                    >
                        {generalError && <LemonBanner type="error">{generalError.detail}</LemonBanner>}
                        <LemonField name="token" label="Authenticator token">
                            <LemonInput
                                className="ph-ignore-input"
                                autoFocus={!passkeysAvailable}
                                data-attr="token"
                                placeholder="123456"
                                inputMode="numeric"
                                autoComplete="one-time-code"
                            />
                        </LemonField>
                        <LemonButton
                            type="primary"
                            status="alt"
                            htmlType="submit"
                            data-attr="2fa-login"
                            fullWidth
                            center
                            loading={isTwofactortokenSubmitting}
                            size="large"
                        >
                            Login
                        </LemonButton>
                    </Form>
                )}

                {!passkeysAvailable && !totpAvailable && (
                    <LemonBanner type="error">
                        No 2FA methods available. Please contact support if you believe this is an error.
                    </LemonBanner>
                )}
            </div>
        </BridgePage>
    )
}

export const scene: SceneExport = {
    component: Login2FA,
    logic: login2FALogic,
}
