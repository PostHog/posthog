import { Menu } from '@base-ui/react/menu'
import { useActions, useValues } from 'kea'

import { IconCopy, IconGear, IconLeave, IconPlusSmall, IconReceipt } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { IconBlank } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'
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
import { ScrollableShadows } from '../ScrollableShadows/ScrollableShadows'
import { OrgModal } from './OrgModal'
import { ProjectModal } from './ProjectModal'
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
    const { setAccountMenuOpen, openProjectSwitcher, openOrgSwitcher } = useActions(newAccountMenuLogic)

    const projectNameStartsWithEmoji = currentTeam?.name?.match(/^\p{Emoji}/u) !== null
    const projectNameWithoutFirstEmoji = projectNameStartsWithEmoji
        ? currentTeam?.name?.replace(/^\p{Emoji}/u, '').trimStart()
        : currentTeam?.name

    return (
        <>
            <Menu.Root open={isAccountMenuOpen} onOpenChange={setAccountMenuOpen}>
                <Menu.Trigger
                    render={(props) => (
                        <ButtonPrimitive
                            {...props}
                            iconOnly={isLayoutNavCollapsed}
                            className={cn('flex-1', {
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
                                    {!isLayoutNavCollapsed && (
                                        <span className="truncate">{projectNameWithoutFirstEmoji ?? 'Project'}</span>
                                    )}
                                </>
                            )}
                            {!isLayoutNavCollapsed && <MenuOpenIndicator />}
                        </ButtonPrimitive>
                    )}
                />

                <Menu.Portal>
                    <Menu.Backdrop />

                    <Menu.Positioner className="z-[var(--z-popover)]" sideOffset={4}>
                        <Menu.Popup className="primitive-menu-content max-h-[calc(var(--available-height)-4px)] min-w-[250px] w-full">
                            <ScrollableShadows
                                direction="vertical"
                                styledScrollbars
                                className="flex flex-col gap-px overflow-x-hidden"
                                innerClassName="primitive-menu-content-inner p-1 "
                            >
                                <Label intent="menu" className="px-2">
                                    Signed in as
                                </Label>
                                <DropdownMenuSeparator />
                                <Menu.Item
                                    render={(props) => (
                                        <Link
                                            {...props}
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
                                    )}
                                />

                                <Label intent="menu" className="px-2 mt-2">
                                    Projects
                                </Label>
                                <DropdownMenuSeparator />

                                {isAuthenticatedTeam(currentTeam) && (
                                    <Menu.Item
                                        render={(props) => (
                                            <Link
                                                {...props}
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
                                                    {String.fromCodePoint(
                                                        currentTeam.name.codePointAt(0)!
                                                    ).toLocaleUpperCase()}
                                                </div>
                                                <span className="truncate font-semibold">
                                                    {currentTeam ? projectNameWithoutFirstEmoji : 'Select project'}
                                                </span>
                                                {currentTeam && (
                                                    <div className="ml-auto flex items-center gap-1">
                                                        <IconGear className="text-tertiary" />
                                                    </div>
                                                )}
                                            </Link>
                                        )}
                                    />
                                )}

                                <Menu.Item
                                    onClick={() => {
                                        showInviteModal()
                                        reportInviteMembersButtonClicked()
                                    }}
                                    render={
                                        <ButtonPrimitive
                                            menuItem
                                            tooltip="Invite members"
                                            tooltipPlacement="right"
                                            data-attr="top-menu-invite-team-members"
                                        >
                                            <IconPlusSmall />
                                            Invite members
                                        </ButtonPrimitive>
                                    }
                                />

                                <Menu.Item
                                    onClick={() => openProjectSwitcher()}
                                    render={
                                        <ButtonPrimitive menuItem data-attr="top-menu-all-projects">
                                            <IconBlank />
                                            All projects
                                            <span className="ml-auto text-tertiary text-xs">
                                                <RenderKeybind keybind={[keyBinds.projectSwitcher]} />
                                            </span>
                                        </ButtonPrimitive>
                                    }
                                />

                                <Label intent="menu" className="px-2 mt-2">
                                    Organizations
                                </Label>
                                <DropdownMenuSeparator />
                                <Menu.Item
                                    render={(props) => (
                                        <Link
                                            {...props}
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
                                    )}
                                />

                                {isCloudOrDev ? (
                                    <Menu.Item
                                        render={(props) => (
                                            <Link
                                                {...props}
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
                                                {featureFlags[FEATURE_FLAGS.USAGE_SPEND_DASHBOARDS]
                                                    ? 'Billing & Usage'
                                                    : 'Billing'}
                                            </Link>
                                        )}
                                    />
                                ) : null}

                                <Menu.Item
                                    onClick={() => {
                                        setAccountMenuOpen(false)
                                        openOrgSwitcher()
                                    }}
                                    render={
                                        <ButtonPrimitive menuItem data-attr="top-menu-all-organizations">
                                            <IconBlank />
                                            All organizations
                                            <span className="ml-auto text-tertiary text-xs">
                                                <RenderKeybind keybind={[keyBinds.orgSwitcher]} />
                                            </span>
                                        </ButtonPrimitive>
                                    }
                                />

                                <DropdownMenuSeparator />

                                {billing?.account_owner?.email && billing?.account_owner?.name && (
                                    <>
                                        <Label intent="menu" className="px-2 mt-2">
                                            YOUR POSTHOG HUMAN
                                        </Label>
                                        <DropdownMenuSeparator />
                                        <Menu.Item
                                            onClick={() => {
                                                void copyToClipboard(billing?.account_owner?.email || '', 'email')
                                                reportAccountOwnerClicked({
                                                    name: billing?.account_owner?.name || '',
                                                    email: billing?.account_owner?.email || '',
                                                })
                                            }}
                                            render={
                                                <ButtonPrimitive
                                                    menuItem
                                                    tooltip="This is your dedicated PostHog human. Click to copy their email. They can help you with trying out new products, solving problems, and reducing your spend."
                                                    tooltipPlacement="right"
                                                    data-attr="top-menu-account-owner"
                                                >
                                                    <ProfilePicture
                                                        user={{
                                                            first_name: billing?.account_owner?.name || '',
                                                            email: billing?.account_owner?.email || '',
                                                        }}
                                                        size="xs"
                                                    />
                                                    <span className="truncate font-semibold">
                                                        {billing?.account_owner?.name || ''}
                                                    </span>
                                                    <div className="ml-auto">
                                                        <IconCopy />
                                                    </div>
                                                </ButtonPrimitive>
                                            }
                                        />
                                        <DropdownMenuSeparator />
                                    </>
                                )}

                                <Menu.Item
                                    onClick={() => logout()}
                                    render={
                                        <ButtonPrimitive menuItem data-attr="top-menu-item-logout">
                                            <IconLeave />
                                            Log out
                                        </ButtonPrimitive>
                                    }
                                />
                            </ScrollableShadows>
                        </Menu.Popup>
                    </Menu.Positioner>
                </Menu.Portal>
                {/* 
                <DropdownMenuContent
                    side="bottom"
                    align="start"
                    collisionPadding={{ bottom: 0 }}
                    className="min-w-[var(--project-panel-width)]"
                >
                    <DropdownMenuGroup>
                    </DropdownMenuGroup>
                </DropdownMenuContent> */}
            </Menu.Root>

            <ProjectModal />
            <OrgModal />
        </>
    )
}
