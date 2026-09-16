import './Setup2FA.scss'

import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { twoFactorLogic } from './twoFactorLogic'

export function TwoFactorSetup({ onSuccess }: { onSuccess: () => void }): JSX.Element | null {
    const { startSetupLoading, startSetup, generalError, isTokenSubmitting } = useValues(twoFactorLogic({ onSuccess }))
    if (startSetupLoading) {
        return null
    }

    return (
        <>
            <Form
                logic={twoFactorLogic}
                formKey="token"
                enableFormOnSubmit
                className="flex flex-col deprecated-space-y-4"
            >
                <div className="flex flex-col items-center">
                    <div className="bg-white p-4 rounded">
                        <img
                            src="/account/two_factor/qrcode/"
                            className="Setup2FA__image"
                            alt="QR code for two-factor authentication setup"
                        />
                    </div>

                    {/* Secret key for manual entry */}
                    {startSetup?.secret && (
                        <div className="ph-no-capture mt-4 p-3 bg-secondary rounded text-center w-full max-w-md">
                            <p className="text-default">
                                If you can't scan the QR code, you can use the secret key below to manually set up your
                                authenticator app.
                            </p>
                            <CopyToClipboardInline description="2FA secret key" selectable iconSize="xsmall">
                                {startSetup.secret}
                            </CopyToClipboardInline>
                        </div>
                    )}
                </div>
                {generalError && <LemonBanner type="error">{generalError.detail}</LemonBanner>}
                <LemonField name="token" label="Authenticator token">
                    {({ value, onChange, id }) => (
                        <LemonInput
                            id={id}
                            className="ph-ignore-input"
                            autoFocus
                            data-attr="token"
                            placeholder="123456"
                            inputMode="numeric"
                            autoComplete="one-time-code"
                            value={value ?? ''}
                            // Password-manager autofill can set the field without firing a React change event.
                            // Read the value on change, blur, and Enter so the store matches what the field shows.
                            // Enter submits the form without blurring, so sync the value before validation runs.
                            onChange={(newValue) => onChange(newValue.replace(/\D/g, ''))}
                            onBlur={(e) => onChange(e.currentTarget.value.replace(/\D/g, ''))}
                            onPressEnter={(e) => onChange(e.currentTarget.value.replace(/\D/g, ''))}
                        />
                    )}
                </LemonField>
                <LemonButton
                    htmlType="submit"
                    data-attr="2fa-setup"
                    fullWidth
                    type="primary"
                    center
                    loading={isTokenSubmitting}
                >
                    Submit
                </LemonButton>
            </Form>
        </>
    )
}
