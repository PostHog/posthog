import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { OrgSwitcher } from 'lib/components/Account/OrgSwitcher'
import { HogWelder } from 'lib/components/hedgehogs'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { SupportModalButton } from 'scenes/authentication/shared/SupportModalButton'
import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

const POLL_INTERVAL_MS = 5000

export const scene: SceneExport = {
    component: OrganizationPendingDeletion,
    logic: organizationLogic,
}

export function OrganizationPendingDeletion(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { loadCurrentOrganization } = useActions(organizationLogic)
    const { otherOrganizations } = useValues(userLogic)
    const { isOrgSwitcherOpen } = useValues(newAccountMenuLogic)
    const { openOrgSwitcher, closeOrgSwitcher } = useActions(newAccountMenuLogic)
    const hasOtherOrgs = otherOrganizations.length > 0

    // Deletion runs asynchronously on the backend, so poll to notice when it finishes instead of
    // leaving the user on a progress screen that never updates.
    useEffect(() => {
        const interval = setInterval(() => loadCurrentOrganization(), POLL_INTERVAL_MS)
        return () => clearInterval(interval)
    }, [loadCurrentOrganization])

    // Redirect only on the transition out of pending deletion (the org finished deleting, or is now
    // gone entirely) so we don't send the user away before the first poll. Hard-navigate to the app
    // root for a clean handoff: another org's home, or organization creation if this was their last.
    const isPendingDeletion = !!currentOrganization?.is_pending_deletion
    const wasPendingDeletionRef = useRef(isPendingDeletion)
    useEffect(() => {
        if (wasPendingDeletionRef.current && !isPendingDeletion) {
            window.location.href = urls.default()
        }
        wasPendingDeletionRef.current = isPendingDeletion
    }, [isPendingDeletion])

    return (
        <div className="max-w-[600px] mx-auto px-2 py-8">
            <LemonCard>
                <div className="flex flex-col gap-4 items-center text-center">
                    <HogWelder className="h-80" />
                    <h3>
                        Disassembling {currentOrganization?.name ? `"${currentOrganization.name}"` : 'all'} data at the
                        circuit level
                    </h3>
                    <p className="text-secondary">
                        Our hedgehog engineer is carefully taking everything apart. Your organization will be completely
                        deleted shortly - this usually takes a couple of minutes.
                    </p>
                    {hasOtherOrgs && (
                        <Popover
                            visible={isOrgSwitcherOpen}
                            onClickOutside={closeOrgSwitcher}
                            overlay={
                                <div className="w-[320px]">
                                    <OrgSwitcher dialog={false} />
                                </div>
                            }
                            placement="bottom"
                        >
                            <LemonButton
                                type="secondary"
                                onClick={() => (isOrgSwitcherOpen ? closeOrgSwitcher() : openOrgSwitcher())}
                                sideIcon={<IconChevronDown />}
                            >
                                {currentOrganization ? (
                                    <span className="flex items-center gap-2">
                                        <UploadedLogo
                                            name={currentOrganization.name}
                                            entityId={currentOrganization.id}
                                            mediaId={currentOrganization.logo_media_id}
                                            size="xsmall"
                                        />
                                        Switch organization
                                    </span>
                                ) : (
                                    'Switch organization'
                                )}
                            </LemonButton>
                        </Popover>
                    )}
                    <SupportModalButton kind="support" label="Contact support" />
                </div>
            </LemonCard>
        </div>
    )
}
