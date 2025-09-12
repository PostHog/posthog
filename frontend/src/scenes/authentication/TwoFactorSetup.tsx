import './Setup2FA.scss'

import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { twoFactorLogic } from './twoFactorLogic'

export function TwoFactorSetup({ onSuccess }: { onSuccess: () => void }): JSX.Element | null {
    const { startSetupLoading, startSetup, generalError } = useValues(twoFactorLogic({ onSuccess }))
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
                <div className="bg-white ml-auto mr-auto">
                    <img src="/account/two_factor/qrcode/" className="Setup2FA__image" />

                    {/* Secret key for manual entry */}
                    {startSetup?.secret && (
                        <div className="mt-4 p-3 bg-gray-50 rounded text-center">
                            <p>
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
                    <LemonInput
                        className="ph-ignore-input"
                        autoFocus
                        data-attr="token"
                        placeholder="123456"
                        inputMode="numeric"
                        autoComplete="one-time-code"
                    />
                </LemonField>
                <LemonButton htmlType="submit" data-attr="2fa-setup" fullWidth type="primary" center loading={false}>
                    Submit
                </LemonButton>
            </Form>
        </>
    )
}
