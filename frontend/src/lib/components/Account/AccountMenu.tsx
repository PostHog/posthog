import { DropdownMenuContentProps } from '@radix-ui/react-dropdown-menu'
import { useActions, useValues } from 'kea'

import {
    IconCake,
    IconConfetti,
    IconCopy,
    IconDay,
    IconFeatures,
    IconGear,
    IconLaptop,
    IconLeave,
    IconLive,
    IconNight,
    IconPalette,
    IconPlusSmall,
    IconReceipt,
    IconServer,
    IconShieldLock,
} from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Link } from 'lib/lemon-ui/Link/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { IconBlank } from 'lib/lemon-ui/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuOpenIndicator,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { Label } from 'lib/ui/Label/Label'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { inviteLogic } from 'scenes/settings/organization/inviteLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { AccessLevelIndicator } from '~/layout/navigation/AccessLevelIndicator'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { getTreeItemsGames } from '~/products'
import { SidePanelTab, UserTheme } from '~/types'

import { OrgCombobox } from './OrgCombobox'

interface AccountMenuProps extends DropdownMenuContentProps {
    trigger: JSX.Element
}

function ThemeMenu(): JSX.Element {
    const { themeMode } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)
    const { customCssEnabled } = useValues(themeLogic)

    function handleThemeChange(theme: UserTheme): void {
        updateUser({ theme_mode: theme })
    }

    return (
        <DropdownMenuSub>
            <DropdownMenuSubTrigger asChild>
                <ButtonPrimitive menuItem>
                    <IconPalette />
                    Color theme
                    <div className="ml-auto flex items-center gap-1">
                        <LemonTag>{themeMode}</LemonTag>
                        <DropdownMenuOpenIndicator intent="sub" />
                    </div>
                </ButtonPrimitive>
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
                <DropdownMenuGroup>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive
                            active={themeMode === 'light'}
                            onClick={() => handleThemeChange('light')}
                            menuItem
                        >
                            <IconDay />
                            Light mode
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive
                            active={themeMode === 'dark'}
                            onClick={() => handleThemeChange('dark')}
                            menuItem
                        >
                            <IconNight />
                            Dark mode
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive
                            active={themeMode === 'system'}
                            onClick={() => handleThemeChange('system')}
                            menuItem
                        >
                            <IconLaptop />
                            Sync with system
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    {customCssEnabled && (
                        <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem asChild>
                                <Link to={urls.customCss()} buttonProps={{ menuItem: true }}>
                                    <IconPalette />
                                    Edit custom CSS
                                </Link>
                            </DropdownMenuItem>
                        </>
                    )}
                </DropdownMenuGroup>
            </DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}

export function AccountMenu({ trigger, ...props }: AccountMenuProps): JSX.Element {
    const { user } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { isCloudOrDev, isCloud } = useValues(preflightLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { billing } = useValues(billingLogic)
    const { showInviteModal } = useActions(inviteLogic)
    const { reportInviteMembersButtonClicked } = useActions(eventUsageLogic)
    const { reportAccountOwnerClicked } = useActions(eventUsageLogic)
    const { logout } = useActions(userLogic)
    const { mobileLayout } = useValues(navigationLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
            <DropdownMenuContent
                {...props}
                collisionPadding={{ bottom: 0 }}
                alignOffset={2}
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

                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger asChild>
                            <ButtonPrimitive menuItem>
                                <IconBlank />
                                Other organizations
                                <DropdownMenuOpenIndicator intent="sub" />
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

                    <ThemeMenu />

                    <DropdownMenuItem asChild>
                        <Link
                            to="https://posthog.com/changelog"
                            buttonProps={{
                                menuItem: true,
                            }}
                            onClick={(e) => {
                                if (!mobileLayout) {
                                    e.preventDefault()
                                    openSidePanel(SidePanelTab.Docs, '/changelog')
                                }
                            }}
                            data-attr="whats-new-button"
                            target="_blank"
                            tooltip="View our changelog"
                            tooltipPlacement="right"
                        >
                            <IconLive />
                            What's new?
                        </Link>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <Link
                            to={urls.settings('user-feature-previews')}
                            buttonProps={{
                                menuItem: true,
                            }}
                            data-attr="top-menu-feature-previews"
                            tooltip="View and access upcoming features"
                            tooltipPlacement="right"
                        >
                            <IconFeatures />
                            Feature previews
                        </Link>
                    </DropdownMenuItem>

                    {featureFlags[FEATURE_FLAGS.GAME_CENTER] && (
                        <DropdownMenuSub>
                            <DropdownMenuSubTrigger asChild>
                                <ButtonPrimitive menuItem>
                                    <IconCake />
                                    Game center
                                    <div className="ml-auto">
                                        <DropdownMenuOpenIndicator intent="sub" />
                                    </div>
                                </ButtonPrimitive>
                            </DropdownMenuSubTrigger>
                            <DropdownMenuSubContent>
                                <DropdownMenuGroup>
                                    {getTreeItemsGames().map((game) => (
                                        <DropdownMenuItem asChild>
                                            <Link to={game.href} buttonProps={{ menuItem: true }}>
                                                {game.path}
                                            </Link>
                                        </DropdownMenuItem>
                                    ))}
                                </DropdownMenuGroup>
                            </DropdownMenuSubContent>
                        </DropdownMenuSub>
                    )}
                    {user?.is_staff && (
                        <>
                            <DropdownMenuItem asChild>
                                <Link
                                    to="/admin/"
                                    buttonProps={{
                                        menuItem: true,
                                    }}
                                    data-attr="top-menu-django-admin"
                                    disableClientSideRouting
                                >
                                    <IconShieldLock />
                                    Django admin
                                </Link>
                            </DropdownMenuItem>
                            <DropdownMenuItem asChild>
                                <Link
                                    to={urls.instanceStatus()}
                                    buttonProps={{
                                        menuItem: true,
                                    }}
                                    tooltip="Async migrations"
                                    tooltipPlacement="right"
                                    data-attr="top-menu-instance-panel"
                                >
                                    <IconServer />
                                    Instance panel
                                </Link>
                            </DropdownMenuItem>
                        </>
                    )}
                    {!isCloud && (
                        <DropdownMenuItem asChild>
                            <Link
                                to={urls.moveToPostHogCloud()}
                                buttonProps={{
                                    menuItem: true,
                                }}
                                data-attr="top-menu-item-upgrade-to-cloud"
                            >
                                <IconConfetti />
                                Try PostHog Cloud
                            </Link>
                        </DropdownMenuItem>
                    )}

                    <DropdownMenuSeparator />

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
