import { setup2FALogic } from './setup2FALogic'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { useValues } from 'kea'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'

export function Setup2FA({ onSuccess }: { onSuccess: () => void }): JSX.Element | null {
    const { startSetupLoading, generalError } = useValues(setup2FALogic({ onSuccess }))
    if (startSetupLoading) {
        return null
    }

    return (
        <>
            <Form logic={setup2FALogic} formKey="token" enableFormOnSubmit className="space-y-4">
                <img src="/account/two_factor/qrcode/" style={{ minWidth: 215, minHeight: 215, margin: 0 }} />
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
                    loading={false}
                >
                    Login
                </LemonButton>
            </Form>
        </>
    )
}
