import { setup2FALogic } from './setup2FALogic'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { useValues } from 'kea'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'
import './Setup2FA.scss'

export function Setup2FA({ onSuccess }: { onSuccess: () => void }): JSX.Element | null {
    const { startSetupLoading, generalError } = useValues(setup2FALogic({ onSuccess }))
    if (startSetupLoading) {
        return null
    }

    return (
        <>
            <Form logic={setup2FALogic} formKey="token" enableFormOnSubmit className="flex flex-col space-y-4">
                <img src="/account/two_factor/qrcode/" className="Setup2FA__image" />
                {generalError && <AlertMessage type="error">{generalError.detail}</AlertMessage>}
                <Field name="token" label="Authenticator token">
                    <LemonInput
                        className="ph-ignore-input"
                        autoFocus
                        data-attr="token"
                        placeholder="123456"
                        type="number"
                        autoComplete="one-time-code"
                    />
                </Field>
                <LemonButton htmlType="submit" data-attr="2fa-setup" fullWidth type="primary" center loading={false}>
                    Login
                </LemonButton>
            </Form>
        </>
    )
}
