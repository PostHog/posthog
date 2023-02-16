import { useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { login2FALogic } from './login2FALogic'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'

export function Login2FA(): JSX.Element {
    const { precheckResponseLoading, isLoginSubmitting, generalError } = useValues(login2FALogic)
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
                    {generalError && <AlertMessage type="error">{generalError.detail}</AlertMessage>}
                    <Field name="token" label="Authenticator token">
                        <LemonInput
                            className="ph-ignore-input"
                            autoFocus
                            data-attr="token"
                            placeholder="123456"
                            type="text"
                            inputMode="numeric"
                            pattern="[0-9]*"
                            autoComplete="one-time-code"
                        />
                    </Field>
                    <LemonButton
                        htmlType="submit"
                        data-attr="password-login"
                        fullWidth
                        type="primary"
                        center
                        loading={isLoginSubmitting || precheckResponseLoading}
                    >
                        Login
                    </LemonButton>
                </Form>
            </div>
        </BridgePage>
    )
}
