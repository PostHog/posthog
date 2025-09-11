import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { login2FALogic } from './login2FALogic'

export function Login2FA(): JSX.Element {
    const { isTwofactortokenSubmitting, generalError } = useValues(login2FALogic)
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
                <p>Enter a token from your authenticator app or a backup code.</p>

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
                            autoFocus
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
            </div>
        </BridgePage>
    )
}
