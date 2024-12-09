import { useActions, useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { twoFactorLogic } from './twoFactorLogic'
import { TwoFactorSetup } from './TwoFactorSetup'

interface TwoFactorSetupModalProps {
    onSuccess: () => void
    closable?: boolean
    required?: boolean
    forceOpen?: boolean
}

export function TwoFactorSetupModal({
    onSuccess,
    closable = true,
    required = false,
    forceOpen = false,
}: TwoFactorSetupModalProps): JSX.Element {
    const { isTwoFactorSetupModalOpen } = useValues(twoFactorLogic)
    const { toggleTwoFactorSetupModal } = useActions(twoFactorLogic)

    return (
        <LemonModal
            title="Set up two-factor authentication"
            isOpen={isTwoFactorSetupModalOpen || forceOpen}
            onClose={closable ? () => toggleTwoFactorSetupModal(false) : undefined}
            closable={closable}
        >
            <div className="max-w-md">
                {required && (
                    <LemonBanner className="mb-4" type="warning">
                        Your organization requires you to set up 2FA.
                    </LemonBanner>
                )}
                <p>Use an authenticator app like Google Authenticator or 1Password to scan the QR code below.</p>
                <TwoFactorSetup
                    onSuccess={() => {
                        toggleTwoFactorSetupModal(false)
                        if (onSuccess) {
                            onSuccess()
                        }
                    }}
                />
            </div>
        </LemonModal>
    )
}
