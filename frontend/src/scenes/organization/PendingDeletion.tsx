import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { OrgSwitcher } from 'lib/components/Account/OrgSwitcher'
import { HogWelder } from 'lib/components/hedgehogs'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { SupportModalButton } from 'scenes/authentication/SupportModalButton'
import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

export const scene: SceneExport = {
    component: OrganizationPendingDeletion,
    logic: organizationLogic,
}

export function OrganizationPendingDeletion(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { otherOrganizations } = useValues(userLogic)
    const { isOrgSwitcherOpen } = useValues(newAccountMenuLogic)
    const { openOrgSwitcher, closeOrgSwitcher } = useActions(newAccountMenuLogic)
    const hasOtherOrgs = otherOrganizations.length > 0

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
                    <SupportModalButton kind="support" target_area="login" label="Contact support" />
                </div>
            </LemonCard>
        </div>
    )
}
