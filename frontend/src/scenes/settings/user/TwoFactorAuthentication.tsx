import { IconCheckCircle, IconCopy, IconWarning } from '@posthog/icons'
import { LemonButton, LemonModal, lemonToast } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { Setup2FA } from 'scenes/authentication/Setup2FA'
import { setup2FALogic } from 'scenes/authentication/setup2FALogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

export function TwoFactorAuthentication(): JSX.Element {
    const { user } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)
    const { loadMemberUpdates } = useActions(membersLogic)
    const [setupModalVisible, setSetupModalVisible] = useState(false)
    const [disableModalVisible, setDisableModalVisible] = useState(false)
    const [backupCodesModalVisible, setBackupCodesModalVisible] = useState(false)
    const { status } = useValues(setup2FALogic)
    const { generateBackupCodes, disable2FA } = useActions(setup2FALogic)

    const handleSuccess = (): void => {
        updateUser({})
        loadMemberUpdates()
    }

    return (
        <div className="flex flex-col items-start">
            {setupModalVisible && (
                <LemonModal title="Set up 2FA" onClose={() => setSetupModalVisible(false)}>
                    <>
                        <b>
                            Use an authenticator app like Google Authenticator or 1Password to scan the QR code below.
                        </b>
                        <Setup2FA
                            onSuccess={() => {
                                setSetupModalVisible(false)
                                handleSuccess()
                            }}
                        />
                    </>
                </LemonModal>
            )}

            {disableModalVisible && (
                <LemonModal
                    title="Disable 2FA"
                    onClose={() => setDisableModalVisible(false)}
                    footer={
                        <>
                            <LemonButton onClick={() => setDisableModalVisible(false)}>Cancel</LemonButton>
                            <LemonButton
                                type="primary"
                                status="danger"
                                onClick={() => {
                                    disable2FA()
                                    setDisableModalVisible(false)
                                    handleSuccess()
                                }}
                            >
                                Disable 2FA
                            </LemonButton>
                        </>
                    }
                >
                    <p>
                        Are you sure you want to disable two-factor authentication? This will make your account less
                        secure.
                    </p>
                </LemonModal>
            )}

            {backupCodesModalVisible && (
                <LemonModal title="Backup Codes" onClose={() => setBackupCodesModalVisible(false)}>
                    <div className="space-y-4 max-w-md">
                        <p>
                            Save these backup codes in a secure location. Each code can only be used once to sign in if
                            you lose access to your authentication device.
                        </p>
                        <div className="bg-bg-3000 p-4 rounded font-mono space-y-1 relative">
                            <LemonButton
                                icon={<IconCopy />}
                                size="small"
                                className="absolute top-4 right-4"
                                onClick={() => {
                                    void navigator.clipboard.writeText(status?.backup_codes.join('\n') || '')
                                    lemonToast.success('Backup codes copied to clipboard')
                                }}
                            >
                                Copy
                            </LemonButton>
                            {status?.backup_codes.map((code) => (
                                <div key={code}>{code}</div>
                            ))}
                        </div>
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                generateBackupCodes()
                            }}
                        >
                            Generate New Codes
                        </LemonButton>
                    </div>
                </LemonModal>
            )}

            {user?.is_2fa_enabled ? (
                <>
                    <div className="mb-2 flex items-center">
                        <IconCheckCircle color="green" className="text-xl mr-2" />
                        <span className="font-medium">2FA enabled</span>
                    </div>
                    <div className="space-x-2 flex items-center">
                        <LemonButton type="secondary" onClick={() => setBackupCodesModalVisible(true)}>
                            View Backup Codes
                        </LemonButton>
                        <LemonButton type="secondary" status="danger" onClick={() => setDisableModalVisible(true)}>
                            Disable 2FA
                        </LemonButton>
                    </div>
                </>
            ) : (
                <div>
                    <div className="mb-2 flex items-center">
                        <IconWarning color="orange" className="text-xl mr-2" />
                        <span className="font-medium">2FA is not enabled</span>
                    </div>
                    <LemonButton type="primary" onClick={() => setSetupModalVisible(true)}>
                        Set up 2FA
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
