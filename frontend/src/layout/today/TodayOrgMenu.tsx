import { useActions, useValues } from 'kea'

import { IconCheck, IconGear, IconPlusSmall, IconReceipt } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { PendingInviteDot } from 'lib/components/Account/ProjectMenu'
import { IconPersonAdd } from 'lib/lemon-ui/icons'
import { organizationLogic } from 'scenes/organizationLogic'

import { TodayLogo } from './TodayLogo'
import { OrgMenuActionKey, todayOrgMenuLogic } from './todayOrgMenuLogic'
import { SEVERITY_INDICATOR, SEVERITY_TEXT_CLASS } from './todayRailSeverity'
import { todayRailStatusLogic } from './todayRailStatusLogic'

interface OrgMenuActionRow {
    label: string
    leading: JSX.Element
    dataAttr: string
}

// pinned: autocapture data-attrs, kept from when this menu sat on the rail.
const ACTION_ROWS: Record<OrgMenuActionKey, OrgMenuActionRow> = {
    'invite-members': { label: 'Invite members', leading: <IconPersonAdd />, dataAttr: 'today-rail-invite-members' },
    billing: { label: 'Billing & usage', leading: <IconReceipt />, dataAttr: 'today-rail-billing' },
    'org-settings': { label: 'Organization settings', leading: <IconGear />, dataAttr: 'today-rail-org-settings' },
    'new-org': { label: 'New organization', leading: <IconPlusSmall />, dataAttr: 'today-rail-new-org' },
}

/** The org switcher shortcut opens this menu too. People rarely have many orgs, so the menu has no search. */
export function TodayOrgMenu(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { orgSeverity, orgProblems, billingSeverity, billingText } = useValues(todayRailStatusLogic)
    const { isOrgSwitcherOpen } = useValues(newAccountMenuLogic)
    const { openOrgSwitcher, closeOrgSwitcher } = useActions(newAccountMenuLogic)
    const { organizations, pendingInvites, orgMenuActions, isSwitchingOrganization } = useValues(todayOrgMenuLogic)
    const { switchOrganization, openInvite, runOrgMenuAction } = useActions(todayOrgMenuLogic)
    const name = currentOrganization?.name ?? 'Select organization'

    return (
        <DropdownMenu open={isOrgSwitcherOpen} onOpenChange={(open) => (open ? openOrgSwitcher() : closeOrgSwitcher())}>
            <Tooltip>
                <TooltipTrigger
                    delay={0}
                    render={
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    size="icon"
                                    indicator={SEVERITY_INDICATOR[orgSeverity]}
                                    aria-label={[name, ...orgProblems].join(', ')}
                                    className="relative size-10 rounded-md [--quill-button-indicator-ring:var(--chrome)] data-[popup-open]:bg-[var(--fill-selected)]"
                                    data-attr="today-rail-org-menu"
                                >
                                    <TodayLogo
                                        name={currentOrganization?.name ?? ''}
                                        mediaId={currentOrganization?.logo_media_id}
                                        colorSeed={currentOrganization?.id ?? null}
                                        size="tile"
                                    />
                                </Button>
                            }
                        />
                    }
                />
                <TooltipContent side="bottom">{name}</TooltipContent>
            </Tooltip>
            <DropdownMenuContent className="w-64">
                <DropdownMenuGroup>
                    {organizations.map((organization) => (
                        <DropdownMenuItem
                            key={organization.id}
                            onClick={() => switchOrganization(organization.id)}
                            disabledReason={
                                isSwitchingOrganization
                                    ? 'Switching organization…'
                                    : 'is_active' in organization && organization.is_active === false
                                      ? 'This organization is inactive'
                                      : null
                            }
                            data-attr="today-rail-org-item"
                        >
                            <TodayLogo
                                name={organization.name}
                                mediaId={organization.logo_media_id}
                                colorSeed={organization.id}
                                size="row"
                            />
                            <span className="min-w-0 truncate">{organization.name}</span>
                            {organization.id === currentOrganization?.id && <IconCheck className="ms-auto" />}
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuGroup>
                {pendingInvites.length > 0 && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>Invitations</DropdownMenuLabel>
                            {pendingInvites.map((invite) => (
                                <DropdownMenuItem
                                    key={invite.id}
                                    onClick={() => openInvite(invite.id)}
                                    data-attr="today-rail-org-invite"
                                >
                                    <span className="min-w-0 truncate">{invite.organization_name}</span>
                                    <PendingInviteDot className="ms-auto" />
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuGroup>
                    </>
                )}
                <DropdownMenuSeparator />
                {orgMenuActions.map((key) => (
                    <DropdownMenuItem
                        key={key}
                        onClick={() => runOrgMenuAction(key)}
                        description={
                            key === 'billing' && billingText ? (
                                <span className={SEVERITY_TEXT_CLASS[billingSeverity]}>{billingText}</span>
                            ) : undefined
                        }
                        data-attr={ACTION_ROWS[key].dataAttr}
                    >
                        {ACTION_ROWS[key].leading}
                        {ACTION_ROWS[key].label}
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
