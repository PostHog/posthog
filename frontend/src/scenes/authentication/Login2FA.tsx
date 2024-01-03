import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { Field } from 'lib/forms/Field'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
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
            <div className="space-y-2">
                <h2>Two-Factor Authentication</h2>
                <p>Enter a token from your authenticator app.</p>

                <Form logic={login2FALogic} formKey="twofactortoken" enableFormOnSubmit className="space-y-4">
                    {generalError && <LemonBanner type="error">{generalError.detail}</LemonBanner>}
                    <Field name="token" label="Authenticator token">
                        <LemonInput
                            className="ph-ignore-input"
                            autoFocus
                            data-attr="token"
                            placeholder="123456"
                            inputMode="numeric"
                            autoComplete="one-time-code"
                        />
                    </Field>
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
