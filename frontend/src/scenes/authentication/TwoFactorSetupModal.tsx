import { useActions, useValues } from 'kea'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

import { twoFactorLogic } from './twoFactorLogic'
import { TwoFactorSetup } from './TwoFactorSetup'

export function TwoFactorSetupModal(): JSX.Element {
    const { isTwoFactorSetupModalOpen, forceOpenTwoFactorSetupModal } = useValues(twoFactorLogic)
    const { closeTwoFactorSetupModal } = useActions(twoFactorLogic)

    return (
        <LemonModal
            title="Set up two-factor authentication"
            isOpen={isTwoFactorSetupModalOpen || forceOpenTwoFactorSetupModal}
            onClose={!forceOpenTwoFactorSetupModal ? () => closeTwoFactorSetupModal() : undefined}
            closable={!forceOpenTwoFactorSetupModal}
        >
            <div className="max-w-md">
                {forceOpenTwoFactorSetupModal && (
                    <LemonBanner className="mb-4" type="warning">
                        Your organization requires you to set up 2FA.
                    </LemonBanner>
                )}
                <p>Use an authenticator app like Google Authenticator or 1Password to scan the QR code below.</p>
                <TwoFactorSetup
                    onSuccess={() => {
                        closeTwoFactorSetupModal()
                        userLogic.actions.loadUser()
                        membersLogic.actions.loadAllMembers()
                    }}
                />
            </div>
        </LemonModal>
    )
}
