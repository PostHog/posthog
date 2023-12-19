import './Setup2FA.scss'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { setup2FALogic } from './setup2FALogic'

export function Setup2FA({ onSuccess }: { onSuccess: () => void }): JSX.Element | null {
    const { startSetupLoading, generalError } = useValues(setup2FALogic({ onSuccess }))
    if (startSetupLoading) {
        return null
    }

    return (
        <>
            <Form logic={setup2FALogic} formKey="token" enableFormOnSubmit className="flex flex-col space-y-4">
                <div className="bg-white ml-auto mr-auto mt-2">
                    <img src="/account/two_factor/qrcode/" className="Setup2FA__image" />
                </div>
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
                <LemonButton htmlType="submit" data-attr="2fa-setup" fullWidth type="primary" center loading={false}>
                    Login
                </LemonButton>
            </Form>
        </>
    )
}
