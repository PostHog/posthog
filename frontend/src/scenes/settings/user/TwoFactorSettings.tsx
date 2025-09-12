import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconCopy, IconWarning } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { twoFactorLogic } from 'scenes/authentication/twoFactorLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

export function TwoFactorSettings(): JSX.Element {
    const { user } = useValues(userLogic)
    const { status, isDisable2FAModalOpen, isBackupCodesModalOpen } = useValues(twoFactorLogic)

    const { updateUser } = useActions(userLogic)
    const { loadMemberUpdates } = useActions(membersLogic)
    const { generateBackupCodes, disable2FA, openTwoFactorSetupModal, toggleDisable2FAModal, toggleBackupCodesModal } =
        useActions(twoFactorLogic)

    const handleSuccess = (): void => {
        updateUser({})
        loadMemberUpdates()
    }

    return (
        <div className="flex flex-col items-start">
            {isDisable2FAModalOpen && (
                <LemonModal
                    title="Disable 2FA"
                    onClose={() => toggleDisable2FAModal(false)}
                    footer={
                        <>
                            <LemonButton onClick={() => toggleDisable2FAModal(false)}>Cancel</LemonButton>
                            <LemonButton
                                type="primary"
                                status="danger"
                                onClick={() => {
                                    disable2FA()
                                    toggleDisable2FAModal(false)
                                    handleSuccess()
                                }}
                            >
                                Disable 2FA
                            </LemonButton>
                        </>
                    }
                >
                    <p>Are you sure you want to disable 2FA authentication? This will make your account less secure.</p>
                </LemonModal>
            )}

            {isBackupCodesModalOpen && (
                <LemonModal title="Backup Codes" onClose={() => toggleBackupCodesModal(false)}>
                    <div className="deprecated-space-y-4 max-w-md">
                        {status?.backup_codes?.length ? (
                            <>
                                <p>
                                    Save these backup codes in a secure location. Each code can only be used once to
                                    sign in if you lose access to your authentication device.
                                </p>
                                <div className="bg-primary p-4 rounded font-mono deprecated-space-y-1 relative">
                                    <LemonButton
                                        icon={<IconCopy />}
                                        size="small"
                                        className="absolute top-4 right-4"
                                        onClick={() => {
                                            void copyToClipboard(status.backup_codes.join('\n') || '', 'backup codes')
                                        }}
                                    >
                                        Copy
                                    </LemonButton>
                                    {status.backup_codes.map((code) => (
                                        <div key={code}>{code}</div>
                                    ))}
                                </div>
                            </>
                        ) : (
                            <div className="bg-primary p-4 rounded font-mono deprecated-space-y-1 relative">
                                <p className="text-secondary mb-0">No backup codes generated</p>
                            </div>
                        )}
                        <LemonButton
                            type="primary"
                            onClick={() => {
                                generateBackupCodes()
                            }}
                        >
                            {status?.backup_codes?.length ? 'Generate new codes' : 'Generate backup codes'}
                        </LemonButton>
                    </div>
                </LemonModal>
            )}

            {user?.is_2fa_enabled ? (
                <>
                    <div className="mb-4 flex items-center deprecated-space-x-2">
                        <IconCheckCircle color="green" className="text-xl" />
                        <span className="font-medium">2FA enabled</span>
                    </div>
                    <div className="deprecated-space-x-2 flex items-center">
                        <LemonButton type="secondary" onClick={() => toggleBackupCodesModal(true)}>
                            View backup codes
                        </LemonButton>
                        <LemonButton type="secondary" status="danger" onClick={() => toggleDisable2FAModal(true)}>
                            Disable 2FA
                        </LemonButton>
                    </div>
                </>
            ) : (
                <div>
                    <div className="mb-4 flex items-center deprecated-space-x-2">
                        <IconWarning color="orange" className="text-xl" />
                        <span className="font-medium">2FA is not enabled</span>
                    </div>
                    <LemonButton type="primary" onClick={() => openTwoFactorSetupModal()}>
                        Set up 2FA
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
