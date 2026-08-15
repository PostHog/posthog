import './Setup2FA.scss'

import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCopy } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { twoFactorLogic } from './twoFactorLogic'

export function TwoFactorSetup({ onSuccess }: { onSuccess: () => void }): JSX.Element | null {
    const { startSetupLoading, startSetup, generalError, setupBackupCodes } = useValues(twoFactorLogic({ onSuccess }))
    if (startSetupLoading) {
        return null
    }

    if (setupBackupCodes?.length) {
        return (
            <div className="flex flex-col deprecated-space-y-4">
                <p className="mb-0">
                    Save these backup codes somewhere safe. Each code signs you in once if you lose access to your
                    authenticator app. You can view them again in your user settings.
                </p>
                <div className="ph-no-capture bg-primary p-4 rounded font-mono deprecated-space-y-1 relative">
                    <LemonButton
                        icon={<IconCopy />}
                        size="small"
                        className="absolute top-4 right-4"
                        onClick={() => {
                            void copyToClipboard(setupBackupCodes.join('\n'), 'backup codes')
                        }}
                    >
                        Copy
                    </LemonButton>
                    {setupBackupCodes.map((code) => (
                        <div key={code}>{code}</div>
                    ))}
                </div>
                <LemonButton
                    type="primary"
                    fullWidth
                    center
                    data-attr="2fa-backup-codes-saved"
                    onClick={() => onSuccess()}
                >
                    I've saved my backup codes
                </LemonButton>
            </div>
        )
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
