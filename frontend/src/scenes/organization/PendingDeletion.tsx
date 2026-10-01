import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { OrgSwitcher } from 'lib/components/Account/OrgSwitcher'
import { HogWelder } from 'lib/components/hedgehogs'
import { dayjs } from 'lib/dayjs'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { SupportModalButton } from 'scenes/authentication/shared/SupportModalButton'
import { organizationLogic } from 'scenes/organizationLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { userLogic } from 'scenes/userLogic'

export const scene: SceneExport = {
    component: OrganizationPendingDeletion,
    logic: organizationLogic,
}

export function OrganizationPendingDeletion(): JSX.Element {
    const { currentOrganization, currentOrganizationLoading, isAdminOrOwner } = useValues(organizationLogic)
    const { cancelOrganizationDeletion } = useActions(organizationLogic)
    const { otherOrganizations } = useValues(userLogic)
    const { isOrgSwitcherOpen } = useValues(newAccountMenuLogic)
    const { openOrgSwitcher, closeOrgSwitcher } = useActions(newAccountMenuLogic)
    const hasOtherOrgs = otherOrganizations.length > 0

    return (
        <div className="max-w-[600px] mx-auto px-2 py-8">
            <LemonCard>
                <div className="flex flex-col gap-4 items-center text-center">
                    <HogWelder className="h-80" />
                    {currentOrganization?.can_cancel_deletion ? (
                        <>
                            <h3>
                                {currentOrganization.name ? `"${currentOrganization.name}"` : 'This organization'} is
                                scheduled for deletion
                            </h3>
                            <p className="text-secondary">
                                We will delete this organization, all of its projects, and all of its data
                                <strong>
                                    {currentOrganization.deletion_scheduled_at
                                        ? ` on ${dayjs(currentOrganization.deletion_scheduled_at).format('MMMM D, YYYY [at] h:mm A')}`
                                        : ' soon'}
                                </strong>
                                .{' '}
                                {isAdminOrOwner
                                    ? 'If you changed your mind, you can cancel the deletion before then.'
                                    : 'To keep it, ask an organization admin to cancel the deletion before then.'}
                            </p>
                            {isAdminOrOwner && (
                                <LemonButton
                                    type="primary"
                                    onClick={() => cancelOrganizationDeletion()}
                                    loading={currentOrganizationLoading}
                                    data-attr="cancel-organization-deletion"
                                >
                                    Cancel organization deletion
                                </LemonButton>
                            )}
                        </>
                    ) : (
                        <>
                            <h3>
                                Disassembling {currentOrganization?.name ? `"${currentOrganization.name}"` : 'all'} data
                                at the circuit level
                            </h3>
                            <p className="text-secondary">
                                Our hedgehog engineer is carefully taking everything apart. Your organization will be
                                completely deleted shortly - this usually takes a couple of minutes.
                            </p>
                        </>
                    )}
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
