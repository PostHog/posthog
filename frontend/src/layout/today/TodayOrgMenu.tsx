import { useActions, useValues } from 'kea'

import { IconGear, IconPlusSmall, IconReceipt } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { pendingInvitesLogic } from 'lib/components/Account/pendingInvitesLogic'
import { PendingInviteDot } from 'lib/components/Account/ProjectMenu'
import { organizationLogic } from 'scenes/organizationLogic'

import { TodayLogo } from './TodayLogo'
import { OrgMenuActionKey, todayOrgMenuLogic } from './todayOrgMenuLogic'
import { TodaySwitcherMenu, TodaySwitcherRow } from './TodaySwitcherMenu'

// Invite IDs and org IDs are both UUIDs, so the prefix keeps their row values apart in one list.
const INVITE_PREFIX = 'invite:'

// pinned: autocapture data-attrs, kept from when this menu sat on the rail.
const ACTION_ROWS: Record<OrgMenuActionKey, Pick<TodaySwitcherRow, 'label' | 'leading' | 'dataAttr'>> = {
    'invite-members': { label: 'Invite members', leading: <IconPlusSmall />, dataAttr: 'today-rail-invite-members' },
    billing: { label: 'Billing & usage', leading: <IconReceipt />, dataAttr: 'today-rail-billing' },
    'org-settings': { label: 'Organization settings', leading: <IconGear />, dataAttr: 'today-rail-org-settings' },
    'new-org': { label: 'New organization', leading: <IconPlusSmall />, dataAttr: 'today-rail-new-org' },
}

/** The org switcher shortcut opens this menu too. */
export function TodayOrgMenu(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { pendingInvites } = useValues(pendingInvitesLogic)
    const { isOrgSwitcherOpen } = useValues(newAccountMenuLogic)
    const { openOrgSwitcher, closeOrgSwitcher } = useActions(newAccountMenuLogic)
    const { organizations, invites, orgMenuActions, orgSearchValue, isSwitchingOrganization } =
        useValues(todayOrgMenuLogic)
    const { setOrgSearchValue, switchOrganization, openInvite, runOrgMenuAction } = useActions(todayOrgMenuLogic)
    const name = currentOrganization?.name ?? 'Select organization'

    return (
        <TodaySwitcherMenu
            trigger={
                <Button
                    size="icon"
                    aria-label={name}
                    className="relative size-10 rounded-md data-[popup-open]:bg-[var(--fill-selected)]"
                    data-attr="today-rail-org-menu"
                >
                    <TodayLogo
                        name={currentOrganization?.name ?? ''}
                        mediaId={currentOrganization?.logo_media_id}
                        colorSeed={currentOrganization?.id ?? null}
                        size="tile"
                    />
                    {pendingInvites.length > 0 && <PendingInviteDot className="absolute top-1 right-1" />}
                </Button>
            }
            triggerTooltip={name}
            open={isOrgSwitcherOpen}
            onOpenChange={(open) => (open ? openOrgSwitcher() : closeOrgSwitcher())}
            searchValue={orgSearchValue}
            onSearchChange={setOrgSearchValue}
            searchPlaceholder="Search organizations"
            noMatchLabel="No organizations match your search"
            groups={[
                {
                    label: 'Organizations',
                    rows: organizations.map((organization) => ({
                        value: organization.id,
                        label: organization.name,
                        leading: (
                            <TodayLogo
                                name={organization.name}
                                mediaId={organization.logo_media_id}
                                colorSeed={organization.id}
                                size="row"
                            />
                        ),
                        dataAttr: 'today-rail-org-item',
                        disabledReason: isSwitchingOrganization
                            ? 'Switching organization…'
                            : 'is_active' in organization && organization.is_active === false
                              ? 'This organization is inactive'
                              : null,
                        onSelect: () => switchOrganization(organization.id),
                    })),
                },
                {
                    label: 'Invitations',
                    rows: invites.map((invite) => ({
                        value: INVITE_PREFIX + invite.id,
                        label: invite.organization_name,
                        trailing: <PendingInviteDot className="ms-auto" />,
                        dataAttr: 'today-rail-org-invite',
                        onSelect: () => openInvite(invite.id),
                    })),
                },
            ]}
            actions={orgMenuActions.map((key) => ({
                value: key,
                ...ACTION_ROWS[key],
                onSelect: () => runOrgMenuAction(key),
            }))}
            selectedValue={currentOrganization?.id ?? null}
            defaultWidth={256}
            resizeKey="today-org-menu"
        />
    )
}
