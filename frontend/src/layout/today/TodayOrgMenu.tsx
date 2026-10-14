import { useActions, useValues } from 'kea'

import { IconGear, IconPlusSmall, IconReceipt } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { pendingInvitesLogic } from 'lib/components/Account/pendingInvitesLogic'
import { PendingInviteDot } from 'lib/components/Account/ProjectMenu'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { globalModalsLogic } from '~/layout/globalModalsLogic'
import { AvailableFeature } from '~/types'

const linkItem = (to: string): JSX.Element => <Button size="row" left render={<LinkPrimitive to={to} />} />

/** The org switcher shortcut opens this menu too. */
export function TodayOrgMenu(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { otherOrganizations } = useValues(userLogic)
    const { updateCurrentOrganization } = useActions(userLogic)
    const { pendingInvites } = useValues(pendingInvitesLogic)
    const { preflight, isCloudOrDev } = useValues(preflightLogic)
    const { billingEntryUrl } = useValues(billingLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { showCreateOrganizationModal } = useActions(globalModalsLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { reportInviteMembersButtonClicked } = useActions(eventUsageLogic)
    const { isOrgSwitcherOpen } = useValues(newAccountMenuLogic)
    const { openOrgSwitcher, closeOrgSwitcher } = useActions(newAccountMenuLogic)
    // A switch reloads the page when it succeeds. Until then, a second pick would race the first.
    const { isSwitchingOrganization: switching } = useValues(userLogic)

    const organizations = [...(currentOrganization ? [currentOrganization] : []), ...otherOrganizations].sort((a, b) =>
        a.name.localeCompare(b.name)
    )

    return (
        <DropdownMenu open={isOrgSwitcherOpen} onOpenChange={(open) => (open ? openOrgSwitcher() : closeOrgSwitcher())}>
            <Tooltip>
                <DropdownMenuTrigger
                    render={
                        <TooltipTrigger
                            delay={0}
                            render={
                                <Button
                                    size="icon"
                                    aria-label={currentOrganization?.name ?? 'Select organization'}
                                    className="relative size-10 rounded-md data-[popup-open]:bg-[var(--fill-selected)]"
                                    data-attr="today-rail-org-menu"
                                />
                            }
                        />
                    }
                >
                    <UploadedLogo
                        name={currentOrganization?.name ?? '?'}
                        entityId={currentOrganization?.id ?? ''}
                        mediaId={currentOrganization?.logo_media_id ?? ''}
                        size="medium"
                    />
                    {pendingInvites.length > 0 && <PendingInviteDot className="absolute top-1 right-1" />}
                </DropdownMenuTrigger>
                <TooltipContent side="right">{currentOrganization?.name ?? 'Select organization'}</TooltipContent>
            </Tooltip>
            <DropdownMenuContent side="bottom" align="start" className="w-64">
                <DropdownMenuGroup>
                    <DropdownMenuLabel>Organizations</DropdownMenuLabel>
                    <DropdownMenuRadioGroup
                        value={currentOrganization?.id ?? ''}
                        onValueChange={(id) => {
                            if (id !== currentOrganization?.id && !switching) {
                                closeOrgSwitcher()
                                updateCurrentOrganization(id as string)
                            }
                        }}
                    >
                        {organizations.map((organization) => (
                            <DropdownMenuRadioItem
                                key={organization.id}
                                value={organization.id}
                                disabled={
                                    switching || ('is_active' in organization && organization.is_active === false)
                                }
                                data-attr="today-rail-org-item"
                            >
                                <UploadedLogo
                                    name={organization.name}
                                    entityId={organization.id}
                                    mediaId={organization.logo_media_id}
                                    size="xsmall"
                                />
                                <span className="min-w-0 truncate">{organization.name}</span>
                            </DropdownMenuRadioItem>
                        ))}
                    </DropdownMenuRadioGroup>
                </DropdownMenuGroup>
                {pendingInvites.length > 0 && (
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Invitations</DropdownMenuLabel>
                        {pendingInvites.map((invite) => (
                            <DropdownMenuItem
                                key={invite.id}
                                onClick={() => {
                                    window.location.href = urls.inviteSignup(invite.id)
                                }}
                                data-attr="today-rail-org-invite"
                            >
                                <span className="min-w-0 truncate">{invite.organization_name}</span>
                                <PendingInviteDot className="ms-auto" />
                            </DropdownMenuItem>
                        ))}
                    </DropdownMenuGroup>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    onClick={() => {
                        showInviteModal()
                        reportInviteMembersButtonClicked()
                    }}
                    data-attr="today-rail-invite-members"
                >
                    <IconPlusSmall />
                    Invite members
                </DropdownMenuItem>
                {isCloudOrDev && billingEntryUrl && (
                    <DropdownMenuItem render={linkItem(billingEntryUrl)} data-attr="today-rail-billing">
                        <IconReceipt />
                        Billing & usage
                    </DropdownMenuItem>
                )}
                <DropdownMenuItem render={linkItem(urls.settings('organization'))} data-attr="today-rail-org-settings">
                    <IconGear />
                    Organization settings
                </DropdownMenuItem>
                {preflight?.can_create_org && (
                    <DropdownMenuItem
                        onClick={() =>
                            guardAvailableFeature(
                                AvailableFeature.ORGANIZATIONS_PROJECTS,
                                () => showCreateOrganizationModal(),
                                { guardOnCloud: false }
                            )
                        }
                        data-attr="today-rail-new-org"
                    >
                        <IconPlusSmall />
                        New organization
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
