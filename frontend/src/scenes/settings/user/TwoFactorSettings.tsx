import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconCopy, IconInfo, IconWarning } from '@posthog/icons'
import { LemonButton, LemonModal, LemonSwitch, Tooltip, lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { twoFactorLogic } from 'scenes/authentication/twoFactorLogic'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

import { UserType } from '~/types'

export function TwoFactorSettings(): JSX.Element {
    const { status, isDisable2FAModalOpen, isBackupCodesModalOpen } = useValues(twoFactorLogic)

    const { updateUser } = useActions(userLogic)
    const { loadMemberUpdates } = useActions(membersLogic)
    const {
        generateBackupCodes,
        disable2FA,
        loadStatus,
        openTwoFactorSetupModal,
        toggleDisable2FAModal,
        toggleBackupCodesModal,
    } = useActions(twoFactorLogic)

    const handleSuccess = (): void => {
        updateUser({})
        loadMemberUpdates()
    }

    const hasTotp = status?.has_totp ?? false
    const hasPasskeys = status?.has_passkeys ?? false
    const passkeysEnabled = status?.passkeys_enabled_for_2fa ?? false

    return (
        <div className="flex flex-col items-start space-y-4">
            {isDisable2FAModalOpen && (
                <LemonModal
                    title="Disable authenticator app"
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
                    <p>
                        Are you sure you want to disable 2FA using an authenticator app? This will make your account
                        less secure.
                    </p>
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

            <div className="space-y-1">
                <p className="text-muted mb-4">
                    Enable two-factor authentication (2FA) to add an extra layer of security to your account. You can
                    use one or both methods below.
                </p>

                {/* 2FA Status Indicator */}
                <div className="mb-4 flex items-center deprecated-space-x-2">
                    {status?.is_enabled ? (
                        <>
                            <IconCheckCircle color="green" className="text-xl" />
                            <span className="font-medium">2FA enabled</span>
                        </>
                    ) : (
                        <>
                            <IconWarning color="orange" className="text-xl" />
                            <span className="font-medium">2FA not enabled</span>
                        </>
                    )}
                </div>

                <div className="border rounded bg-bg-light">
                    {/* Authenticator app row */}
                    <div className="p-4 border-b last:border-b-0">
                        <div className="flex items-center justify-between">
                            <div className="flex-1">
                                <div className="flex items-center gap-2 mb-1">
                                    <span className="font-medium">Authenticator app</span>
                                    <Tooltip
                                        title={
                                            <div className="space-y-2">
                                                <p>
                                                    Use an authenticator app (like Google Authenticator, Authy, or
                                                    1Password) to generate time-based codes for 2FA.
                                                </p>
                                                <p>
                                                    When enabled, you'll be asked for a code from your authenticator app
                                                    when signing in.
                                                </p>
                                            </div>
                                        }
                                    >
                                        <IconInfo className="text-muted text-sm" />
                                    </Tooltip>
                                </div>
                                <p className="text-sm text-muted">
                                    {hasTotp
                                        ? 'Authenticator app is set up and enabled for 2FA.'
                                        : 'Set up an authenticator app to use time-based codes for 2FA.'}
                                </p>
                            </div>
                            <div className="ml-4 flex items-center gap-2">
                                {hasTotp ? (
                                    <>
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={() => toggleBackupCodesModal(true)}
                                        >
                                            View backup codes
                                        </LemonButton>
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            status="danger"
                                            onClick={() => toggleDisable2FAModal(true)}
                                        >
                                            Disable
                                        </LemonButton>
                                    </>
                                ) : (
                                    <LemonButton type="primary" onClick={() => openTwoFactorSetupModal()}>
                                        Setup
                                    </LemonButton>
                                )}
                            </div>
                        </div>
                    </div>

                    {/* Passkeys row */}
                    <div className={`p-4 ${!hasPasskeys ? 'opacity-60' : ''}`}>
                        <div className="flex items-center justify-between">
                            <div className="flex-1">
                                <div className="flex items-center gap-2 mb-1">
                                    <span className={`font-medium ${!hasPasskeys ? 'text-muted' : ''}`}>Passkeys</span>
                                    <Tooltip
                                        title={
                                            <div className="space-y-2">
                                                <p>
                                                    Passkeys provide a secure, passwordless way to sign in and can be
                                                    used for 2FA authentication.
                                                </p>
                                                <p>
                                                    {hasPasskeys
                                                        ? 'You have passkeys set up. They are automatically used for 2FA when available.'
                                                        : 'Add a passkey in the Passkeys settings to enable this method for 2FA.'}
                                                </p>
                                            </div>
                                        }
                                    >
                                        <IconInfo className="text-muted text-sm" />
                                    </Tooltip>
                                </div>
                                <p className={`text-sm ${!hasPasskeys ? 'text-muted' : 'text-muted'}`}>
                                    {hasPasskeys
                                        ? passkeysEnabled
                                            ? 'Passkeys are enabled for 2FA. Manage your passkeys in the Passkeys settings.'
                                            : 'Passkeys are disabled for 2FA. Enable the switch above to use passkeys for 2FA.'
                                        : 'No passkeys set up. Add a passkey to use this method for 2FA.'}
                                </p>
                            </div>
                            <div className="ml-4">
                                <LemonSwitch
                                    checked={passkeysEnabled}
                                    disabledReason={
                                        !hasPasskeys
                                            ? 'Add a passkey in Passkeys settings to enable this method'
                                            : undefined
                                    }
                                    onChange={async () => {
                                        if (hasPasskeys) {
                                            try {
                                                await updateUser(
                                                    {
                                                        passkeys_enabled_for_2fa: !passkeysEnabled,
                                                    } as Partial<UserType>,
                                                    () => {
                                                        // Reload 2FA status after successful update
                                                        loadStatus()
                                                    }
                                                )
                                            } catch (e: any) {
                                                const { detail } = e as Record<string, any>
                                                lemonToast.error(detail || 'Failed to update passkey 2FA setting')
                                            }
                                        }
                                    }}
                                    tooltip={
                                        hasPasskeys
                                            ? passkeysEnabled
                                                ? 'Disable passkeys for 2FA'
                                                : 'Enable passkeys for 2FA'
                                            : 'Add a passkey to enable this method'
                                    }
                                    size="medium"
                                />
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
