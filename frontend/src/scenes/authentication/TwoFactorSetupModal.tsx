import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonDivider } from '@posthog/lemon-ui'

import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { membersLogic } from 'scenes/organization/membersLogic'
import { userLogic } from 'scenes/userLogic'

import { OrganizationDropdownMenu } from '~/layout/panel-layout/OrganizationDropdownMenu'

import { TwoFactorSetup } from './TwoFactorSetup'
import { twoFactorLogic } from './twoFactorLogic'

export function TwoFactorSetupModal(): JSX.Element {
    const { isTwoFactorSetupModalOpen, forceOpenTwoFactorSetupModal, startSetup, canSwitchOrg } =
        useValues(twoFactorLogic)
    const { closeTwoFactorSetupModal } = useActions(twoFactorLogic)
    const [showOrgDropdown, setShowOrgDropdown] = useState(false)

    // Determine if this is setup mode (has secret) or verification mode (no secret)
    const isSetupMode = !!startSetup?.secret
    const title = isSetupMode ? 'Set up two-factor authentication' : 'Two-factor authentication required'

    return (
        <LemonModal
            title={title}
            isOpen={isTwoFactorSetupModalOpen || forceOpenTwoFactorSetupModal}
            onClose={!forceOpenTwoFactorSetupModal ? () => closeTwoFactorSetupModal() : undefined}
            closable={!forceOpenTwoFactorSetupModal}
        >
            <div className="max-w-md">
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
                <TwoFactorSetup
                    onSuccess={() => {
                        closeTwoFactorSetupModal()
                        userLogic.actions.loadUser()
                        membersLogic.actions.loadAllMembers()
                    }}
                />

                <LemonDivider />

                {canSwitchOrg && (
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
                        {showOrgDropdown && <OrganizationDropdownMenu allowCreate={false} />}
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
