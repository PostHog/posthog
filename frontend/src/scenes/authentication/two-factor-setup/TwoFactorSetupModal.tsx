import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonDivider } from '@posthog/lemon-ui'

import { OrganizationMenu } from 'lib/components/Account/OrganizationMenu'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

import { twoFactorLogic } from './twoFactorLogic'
import { TwoFactorSetup } from './TwoFactorSetup'

export function TwoFactorSetupModal(): JSX.Element {
    const { isTwoFactorSetupModalOpen, forceOpenTwoFactorSetupModal, startSetup, canSwitchOrg, setupBackupCodes } =
        useValues(twoFactorLogic)
    const { closeTwoFactorSetupModal } = useActions(twoFactorLogic)
    const [showOrgDropdown, setShowOrgDropdown] = useState(false)

    // Determine if this is setup mode (has secret) or verification mode (no secret)
    const isSetupMode = !!startSetup?.secret
    const showingBackupCodes = setupBackupCodes.length > 0
    const setupTitle = isSetupMode ? 'Set up two-factor authentication' : 'Two-factor authentication required'
    const title = showingBackupCodes ? 'Save your backup codes' : setupTitle
    // Closing the modal here would skip past the codes before the user has saved them.
    const closable = !forceOpenTwoFactorSetupModal && !showingBackupCodes

    return (
        <LemonModal
            title={title}
            isOpen={isTwoFactorSetupModalOpen || forceOpenTwoFactorSetupModal}
            onClose={closable ? () => closeTwoFactorSetupModal() : undefined}
            closable={closable}
        >
            <div className="max-w-md">
                {!showingBackupCodes && (
                    <>
                        {forceOpenTwoFactorSetupModal && (
                            <LemonBanner className="mb-4" type="warning">
                                {isSetupMode
                                    ? 'Your organization requires you to set up 2FA.'
                                    : 'Your organization requires two-factor authentication. Please verify using your authenticator app.'}
                            </LemonBanner>
                        )}
                        <p>
                            {isSetupMode
                                ? 'Use an authenticator app like Google Authenticator or 1Password to scan the QR code below.'
                                : 'Enter the 6-digit code from your authenticator app to verify your identity.'}
                        </p>
                    </>
                )}
                <TwoFactorSetup
                    onSuccess={() => {
                        closeTwoFactorSetupModal()
                        userLogic.actions.loadUser()
                        membersLogic.actions.loadAllMembers()
                    }}
                />

                {canSwitchOrg && !showingBackupCodes && (
                    <>
                        <LemonDivider />
                        <div className="flex flex-col items-center gap-1 mt-4">
                            <div className="text-muted-alt text-xs">
                                or{' '}
                                <button
                                    type="button"
                                    className="text-muted-alt cursor-pointer underline hover:text-muted"
                                    onClick={() => setShowOrgDropdown(true)}
                                >
                                    change your organization
                                </button>
                            </div>
                            {showOrgDropdown && <OrganizationMenu allowCreate={false} />}
                        </div>
                    </>
                )}
            </div>
        </LemonModal>
    )
}
