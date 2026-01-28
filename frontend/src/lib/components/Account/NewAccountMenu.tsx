import { useActions, useValues } from 'kea'

import { IconCopy, IconEllipsis, IconGear, IconLeave, IconPlusSmall, IconReceipt } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { Label } from 'lib/ui/Label/Label'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { cn } from 'lib/utils/css-classes'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AccessLevelIndicator } from '~/layout/navigation/AccessLevelIndicator'

import { RenderKeybind } from '../AppShortcuts/AppShortcutMenu'
import { keyBinds } from '../AppShortcuts/shortcuts'
import { OrgCombobox } from './OrgCombobox'
import { ProjectCombobox } from './ProjectCombobox'
import { newAccountMenuLogic } from './newAccountMenuLogic'

interface AccountMenuProps {
    isLayoutNavCollapsed: boolean
}

export function NewAccountMenu({ isLayoutNavCollapsed }: AccountMenuProps): JSX.Element {
    const { user } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { billing } = useValues(billingLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { reportInviteMembersButtonClicked } = useActions(eventUsageLogic)
    const { reportAccountOwnerClicked } = useActions(eventUsageLogic)
    const { logout } = useActions(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { isAccountMenuOpen } = useValues(newAccountMenuLogic)
    const { setAccountMenuOpen } = useActions(newAccountMenuLogic)

    return (
        <DropdownMenu open={isAccountMenuOpen} onOpenChange={setAccountMenuOpen}>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive
                    tooltip={
                        <div className="flex flex-col gap-1">
                            <p className="m-0">Organization: {currentOrganization?.name}</p>
                            <p className="m-0">Project: {currentTeam?.name}</p>
                            <p className="m-0">
                                <RenderKeybind keybind={[keyBinds.newAccountMenu]} />
                            </p>
                        </div>
                    }
                    tooltipPlacement="right"
                    iconOnly={isLayoutNavCollapsed}
                    className={cn('max-w-[175px]', {
                        'pl-[3px] gap-[6px]': !isLayoutNavCollapsed,
                    })}
                    variant="panel"
                    data-attr="menu-item-me"
                >
                    {isAuthenticatedTeam(currentTeam) && (
                        <>
                            <div
                                className={cn(
                                    'Lettermark bg-[var(--color-bg-fill-button-tertiary-active)] size-5 dark:text-tertiary',
                                    {
                                        'size-[30px] rounded': isLayoutNavCollapsed,
                                    }
                                )}
                            >
                                {String.fromCodePoint(currentTeam.name.codePointAt(0)!).toLocaleUpperCase()}
                            </div>
                            {!isLayoutNavCollapsed && <span className="truncate">{currentTeam.name ?? 'Project'}</span>}
                        </>
                    )}
                    {!isLayoutNavCollapsed && <MenuOpenIndicator />}
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent
                side="bottom"
                align="start"
                collisionPadding={{ bottom: 0 }}
                className="min-w-[var(--project-panel-width)]"
            >
                <DropdownMenuGroup>
                    <Label intent="menu" className="px-2">
                        Signed in as
                    </Label>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild>
                        <Link
                            to={urls.settings(user?.organization?.id ? 'user' : 'user-danger-zone')}
                            buttonProps={{
                                className: 'flex items-center gap-2 h-fit',
                                menuItem: true,
                                truncate: true,
                            }}
                            tooltip="Account settings"
                            tooltipPlacement="right"
                            data-attr="top-menu-account-owner"
                        >
                            <ProfilePicture user={user} size="xs" />
                            <span className="flex flex-col truncate">
                                <span className="font-semibold truncate">{user?.first_name}</span>
                                <span className="text-tertiary text-xs truncate">{user?.email}</span>
                            </span>
                            <div className="ml-auto">
                                <IconGear className="text-tertiary" />
                            </div>
                        </Link>
                    </DropdownMenuItem>

                    <Label intent="menu" className="px-2 mt-2">
                        Projects
                    </Label>
                    <DropdownMenuSeparator />

                    {isAuthenticatedTeam(currentTeam) && (
                        <DropdownMenuItem asChild>
                            <Link
                                to={urls.settings('project')}
                                buttonProps={{
                                    className: 'flex items-center gap-2',
                                    menuItem: true,
                                    truncate: true,
                                }}
                                tooltip="Project settings"
                                tooltipPlacement="right"
                                data-attr="top-menu-project-settings"
                            >
                                <div className="Lettermark bg-[var(--color-bg-fill-button-tertiary-active)] size-4 dark:text-tertiary text-[8px]">
                                    {String.fromCodePoint(currentTeam.name.codePointAt(0)!).toLocaleUpperCase()}
                                </div>
                                <span className="truncate font-semibold">
                                    {currentTeam ? currentTeam.name : 'Select project'}
                                </span>
                                {currentTeam && (
                                    <div className="ml-auto flex items-center gap-1">
                                        <IconGear className="text-tertiary" />
                                    </div>
                                )}
                            </Link>
                        </DropdownMenuItem>
                    )}

                    <DropdownMenuItem asChild>
                        <ButtonPrimitive
                            onClick={() => {
                                showInviteModal()
                                reportInviteMembersButtonClicked()
                            }}
                            menuItem
                            tooltip="Invite members"
                            tooltipPlacement="right"
                            data-attr="top-menu-invite-team-members"
                        >
                            <IconPlusSmall />
                            Invite members
                        </ButtonPrimitive>
                    </DropdownMenuItem>

                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger asChild>
                            <ButtonPrimitive menuItem>
                                <IconEllipsis className="text-tertiary p-px" />
                                Other
                                <MenuOpenIndicator intent="sub" />
                            </ButtonPrimitive>
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent className="min-w-[var(--project-panel-width)]">
                            <ProjectCombobox />
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>

                    <Label intent="menu" className="px-2 mt-2">
                        Organizations
                    </Label>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild>
                        <Link
                            to={urls.settings('organization')}
                            buttonProps={{
                                className: 'flex items-center gap-2',
                                menuItem: true,
                                truncate: true,
                            }}
                            tooltip="Organization settings"
                            tooltipPlacement="right"
                            data-attr="top-menu-organization-settings"
                        >
                            {currentOrganization ? (
                                <UploadedLogo
                                    name={currentOrganization.name}
                                    entityId={currentOrganization.id}
                                    mediaId={currentOrganization.logo_media_id}
                                    size="xsmall"
                                />
                            ) : (
                                <UploadedLogo name="?" entityId="" mediaId="" size="xsmall" />
                            )}
                            <span className="truncate font-semibold">
                                {currentOrganization ? currentOrganization.name : 'Select organization'}
                            </span>
                            {currentOrganization && (
                                <div className="ml-auto flex items-center gap-1">
                                    <AccessLevelIndicator organization={currentOrganization} />
                                    <IconGear className="text-tertiary" />
                                </div>
                            )}
                        </Link>
                    </DropdownMenuItem>

                    {isCloudOrDev ? (
                        <DropdownMenuItem asChild>
                            <Link
                                to={
                                    featureFlags[FEATURE_FLAGS.USAGE_SPEND_DASHBOARDS]
                                        ? urls.organizationBillingSection('overview')
                                        : urls.organizationBilling()
                                }
                                buttonProps={{
                                    className: 'flex items-center gap-2',
                                    menuItem: true,
                                    truncate: true,
                                }}
                            >
                                <IconReceipt />
                                {featureFlags[FEATURE_FLAGS.USAGE_SPEND_DASHBOARDS] ? 'Billing & Usage' : 'Billing'}
                            </Link>
                        </DropdownMenuItem>
                    ) : null}

                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger asChild>
                            <ButtonPrimitive menuItem>
                                <IconEllipsis className="text-tertiary p-px" />
                                Other
                                <MenuOpenIndicator intent="sub" />
                            </ButtonPrimitive>
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent className="min-w-[var(--project-panel-width)]">
                            <OrgCombobox />
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>

                    <DropdownMenuSeparator />

                    {billing?.account_owner?.email && billing?.account_owner?.name && (
                        <>
                            <Label intent="menu" className="px-2 mt-2">
                                YOUR POSTHOG HUMAN
                            </Label>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem asChild>
                                <ButtonPrimitive
                                    menuItem
                                    onClick={() => {
                                        void copyToClipboard(billing?.account_owner?.email || '', 'email')
                                        reportAccountOwnerClicked({
                                            name: billing?.account_owner?.name || '',
                                            email: billing?.account_owner?.email || '',
                                        })
                                    }}
                                    tooltip="This is your dedicated PostHog human. Click to copy their email. They can help you with trying out new products, solving problems, and reducing your spend."
                                    tooltipPlacement="right"
                                    data-attr="top-menu-account-owner"
                                >
                                    <ProfilePicture
                                        user={{
                                            first_name: billing.account_owner.name,
                                            email: billing.account_owner.email,
                                        }}
                                        size="xs"
                                    />
                                    <span className="truncate font-semibold">{billing.account_owner.name}</span>
                                    <div className="ml-auto">
                                        <IconCopy />
                                    </div>
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                        </>
                    )}

                    <DropdownMenuItem asChild>
                        <ButtonPrimitive menuItem onClick={logout} data-attr="top-menu-item-logout">
                            <IconLeave />
                            Log out
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
