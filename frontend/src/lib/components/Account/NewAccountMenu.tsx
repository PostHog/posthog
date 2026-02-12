import { Menu } from '@base-ui/react/menu'
import { useActions, useValues } from 'kea'

import { IconGear, IconLeave, IconPlusSmall, IconReceipt } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { Label } from 'lib/ui/Label/Label'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import { cn } from 'lib/utils/css-classes'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { isAuthenticatedTeam, teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { globalModalsLogic } from '~/layout/GlobalModals'
import { AvailableFeature } from '~/types'

import { RenderKeybind } from '../AppShortcuts/AppShortcutMenu'
import { keyBinds } from '../AppShortcuts/shortcuts'
import { ScrollableShadows } from '../ScrollableShadows/ScrollableShadows'
import { upgradeModalLogic } from '../UpgradeModal/upgradeModalLogic'
import { OrgModal } from './OrgModal'
import { OrgSwitcher } from './OrgSwitcher'
import { ProjectModal } from './ProjectModal'
import { ProjectSwitcher } from './ProjectSwitcher'
import { newAccountMenuLogic } from './newAccountMenuLogic'

interface AccountMenuProps {
    isLayoutNavCollapsed: boolean
}

export function NewAccountMenu({ isLayoutNavCollapsed }: AccountMenuProps): JSX.Element {
    const { user } = useValues(userLogic)
    const { isCloudOrDev } = useValues(preflightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { reportInviteMembersButtonClicked } = useActions(eventUsageLogic)
    const { logout } = useActions(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { isAccountMenuOpen } = useValues(newAccountMenuLogic)
    const { setAccountMenuOpen } = useActions(newAccountMenuLogic)
    const { preflight } = useValues(preflightLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { showCreateProjectModal } = useActions(globalModalsLogic)
    const { showCreateOrganizationModal } = useActions(globalModalsLogic)

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
                            className={cn('flex-1 py-1', {
                                'pl-[3px] gap-[6px]': !isLayoutNavCollapsed,
                            })}
                            variant="panel"
                            data-attr="menu-item-me"
                            tooltip={
                                <div className="flex flex-col gap-1">
                                    <div>
                                        Account menu
                                        <RenderKeybind keybind={[keyBinds.newAccountMenu]} className="ml-1" />
                                    </div>
                                    <div>
                                        Organization:{' '}
                                        {currentOrganization ? currentOrganization.name : 'Select organization'}
                                    </div>
                                    <div>Project: {currentTeam ? currentTeam.name : 'Select project'}</div>
                                </div>
                            }
                        >
                            {isAuthenticatedTeam(currentTeam) && (
                                <>
                                    {currentOrganization ? (
                                        <UploadedLogo
                                            name={currentOrganization.name}
                                            entityId={currentOrganization.id}
                                            mediaId={currentOrganization.logo_media_id}
                                            size="small"
                                        />
                                    ) : (
                                        <UploadedLogo name="?" entityId="" mediaId="" size="xsmall" />
                                    )}

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
                    <Menu.Backdrop className="fixed inset-0 z-[var(--z-modal)]" />

                    <Menu.Positioner className="z-[var(--z-popover)]" sideOffset={4}>
                        <Menu.Popup className="primitive-menu-content max-h-[calc(var(--available-height)-4px)] min-w-[250px] w-full">
                            <ScrollableShadows
                                direction="vertical"
                                styledScrollbars
                                className="flex flex-col gap-px overflow-x-hidden"
                                innerClassName="primitive-menu-content-inner p-1 "
                            >
                                <Label intent="menu" className="pl-2 relative">
                                    Project
                                    {preflight?.can_create_org && (
                                        <ButtonPrimitive
                                            iconOnly
                                            tooltip="Create a new project"
                                            size="xs"
                                            className="absolute -right-[2px] -top-[2px]"
                                            data-attr="new-project-button"
                                            onClick={() => {
                                                guardAvailableFeature(
                                                    AvailableFeature.ORGANIZATIONS_PROJECTS,
                                                    () => {
                                                        setAccountMenuOpen(false)
                                                        showCreateProjectModal()
                                                    },
                                                    { currentUsage: currentOrganization?.teams?.length }
                                                )
                                            }}
                                        >
                                            <IconPlusSmall className="text-tertiary size-4" />
                                        </ButtonPrimitive>
                                    )}
                                </Label>
                                <DropdownMenuSeparator />

                                {isAuthenticatedTeam(currentTeam) && (
                                    <Menu.SubmenuRoot>
                                        <Menu.SubmenuTrigger
                                            render={
                                                <ButtonPrimitive menuItem data-attr="top-menu-all-projects">
                                                    <div className="Lettermark bg-[var(--color-bg-fill-button-tertiary-active)] size-4 dark:text-tertiary text-[8px]">
                                                        {String.fromCodePoint(
                                                            currentTeam.name.codePointAt(0)!
                                                        ).toLocaleUpperCase()}
                                                    </div>
                                                    <span className="truncate font-semibold">
                                                        {currentTeam ? projectNameWithoutFirstEmoji : 'Select project'}
                                                    </span>
                                                    <MenuOpenIndicator intent="sub" className="ml-auto" />
                                                </ButtonPrimitive>
                                            }
                                        />
                                        <Menu.Portal>
                                            <Menu.Positioner
                                                className="z-[var(--z-popover)]"
                                                collisionPadding={{ top: 50, bottom: 50 }}
                                            >
                                                <Menu.Popup className="primitive-menu-content">
                                                    {/* We need to add a div here to prevent the keydown event from bubbling up to the menu. */}
                                                    <div onKeyDown={(e) => e.stopPropagation()}>
                                                        <ProjectSwitcher dialog={false} />
                                                    </div>
                                                </Menu.Popup>
                                            </Menu.Positioner>
                                        </Menu.Portal>
                                    </Menu.SubmenuRoot>
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
                                    render={
                                        <Link
                                            buttonProps={{
                                                menuItem: true,
                                            }}
                                            tooltip="Invite members"
                                            tooltipPlacement="right"
                                            data-attr="top-menu-invite-team-members"
                                        >
                                            <IconGear />
                                            Project settings
                                        </Link>
                                    }
                                />

                                <Label intent="menu" className="px-2 mt-2 relative">
                                    Organization
                                    {preflight?.can_create_org && (
                                        <ButtonPrimitive
                                            iconOnly
                                            tooltip="Create a new organization"
                                            size="xs"
                                            className="absolute right-0 -top-1 p-0"
                                            data-attr="new-organization-button"
                                            onClick={() => {
                                                guardAvailableFeature(
                                                    AvailableFeature.ORGANIZATIONS_PROJECTS,
                                                    () => {
                                                        setAccountMenuOpen(false)
                                                        showCreateOrganizationModal()
                                                    },
                                                    { guardOnCloud: false }
                                                )
                                            }}
                                        >
                                            <IconPlusSmall className="text-tertiary size-4" />
                                        </ButtonPrimitive>
                                    )}
                                </Label>
                                <DropdownMenuSeparator />
                                <Menu.SubmenuRoot>
                                    <Menu.SubmenuTrigger
                                        render={
                                            <ButtonPrimitive menuItem data-attr="top-menu-all-organizations">
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
                                                    {currentOrganization
                                                        ? currentOrganization.name
                                                        : 'Select organization'}
                                                </span>
                                                <MenuOpenIndicator intent="sub" className="ml-auto" />
                                            </ButtonPrimitive>
                                        }
                                    />
                                    <Menu.Portal>
                                        <Menu.Positioner
                                            className="z-[var(--z-popover)]"
                                            collisionPadding={{ top: 50, bottom: 50 }}
                                        >
                                            <Menu.Popup className="primitive-menu-content">
                                                {/* We need to add a div here to prevent the keydown event from bubbling up to the menu. */}
                                                <div onKeyDown={(e) => e.stopPropagation()}>
                                                    <OrgSwitcher dialog={false} />
                                                </div>
                                            </Menu.Popup>
                                        </Menu.Positioner>
                                    </Menu.Portal>
                                </Menu.SubmenuRoot>

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
                                                    ? 'Billing & usage'
                                                    : 'Billing'}
                                            </Link>
                                        )}
                                    />
                                ) : null}

                                <Menu.Item
                                    render={(props) => (
                                        <Link
                                            {...props}
                                            to={urls.settings('organization')}
                                            buttonProps={{
                                                menuItem: true,
                                            }}
                                            tooltip="Organization settings"
                                            tooltipPlacement="right"
                                            data-attr="top-menu-organization-settings"
                                        >
                                            <IconGear />
                                            Organization settings
                                        </Link>
                                    )}
                                />

                                <Label intent="menu" className="px-2 mt-2">
                                    Account
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
                                            tooltip="User settings"
                                            tooltipPlacement="right"
                                            data-attr="top-menu-account-owner"
                                        >
                                            <ProfilePicture user={user} size="xs" />
                                            <span className="flex flex-col truncate">
                                                <span className="font-semibold truncate">{user?.first_name}</span>
                                                <span className="text-tertiary text-xs truncate">{user?.email}</span>
                                            </span>
                                        </Link>
                                    )}
                                />

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
            </Menu.Root>

            <ProjectModal />
            <OrgModal />
        </>
    )
}
