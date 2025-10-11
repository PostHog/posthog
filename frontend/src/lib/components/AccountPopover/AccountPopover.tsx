import { DropdownMenuContentProps, DropdownMenuGroup, DropdownMenuSubTrigger } from '@radix-ui/react-dropdown-menu'
import { useActions, useValues } from 'kea'

import {
    IconCheck,
    IconConfetti,
    IconCopy,
    IconDay,
    IconFeatures,
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
import { Link } from 'lib/lemon-ui/Link/Link'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { IconBlank } from 'lib/lemon-ui/icons/icons'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuOpenIndicator,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
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

import { globalModalsLogic } from '~/layout/GlobalModals'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { AccessLevelIndicator } from '~/layout/navigation/AccessLevelIndicator'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { AvailableFeature, SidePanelTab, UserTheme } from '~/types'

import { upgradeModalLogic } from '../UpgradeModal/upgradeModalLogic'

interface AccountPopoverProps extends DropdownMenuContentProps {
    trigger: JSX.Element
}

function ThemeDropdown(): JSX.Element {
    const { themeMode } = useValues(userLogic)
    const { updateUser } = useActions(userLogic)
    const { customCssEnabled } = useValues(themeLogic)

    function handleThemeChange(theme: UserTheme): void {
        updateUser({ theme_mode: theme })
    }

    return (
        <DropdownMenuSub>
            <DropdownMenuSubTrigger>
                <ButtonPrimitive menuItem>
                    <IconPalette />
                    Color theme {themeMode}
                    <DropdownMenuOpenIndicator intent="sub" />
                </ButtonPrimitive>
            </DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
                <DropdownMenuItem asChild>
                    <ButtonPrimitive active={themeMode === 'light'} onClick={() => handleThemeChange('light')} menuItem>
                        <IconDay />
                        Light mode
                    </ButtonPrimitive>
                </DropdownMenuItem>
                <DropdownMenuItem asChild>
                    <ButtonPrimitive active={themeMode === 'dark'} onClick={() => handleThemeChange('dark')} menuItem>
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
                    <DropdownMenuItem asChild>
                        <Link to={urls.customCss()}>
                            <IconPalette />
                            Edit custom CSS
                        </Link>
                    </DropdownMenuItem>
                )}
            </DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}

export function AccountPopover({ trigger, ...props }: AccountPopoverProps): JSX.Element {
    const { user } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { preflight, isCloudOrDev, isCloud } = useValues(preflightLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { closeAccountPopover } = useActions(navigationLogic)
    const { showCreateOrganizationModal } = useActions(globalModalsLogic)
    const { otherOrganizations } = useValues(userLogic)
    const { updateCurrentOrganization } = useActions(userLogic)
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
            <DropdownMenuContent {...props}>
                <DropdownMenuGroup>
                    <Label intent="menu" className="px-2">
                        Signed in as
                    </Label>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem asChild>
                        <Link
                            to={urls.settings(user?.organization?.id ? 'user' : 'user-danger-zone')}
                            buttonProps={{
                                className: 'flex items-center gap-2',
                                menuItem: true,
                                truncate: true,
                            }}
                        >
                            <ProfilePicture user={user} size="xs" />
                            {user?.first_name ? <span>{user?.first_name}</span> : <span>{user?.email}</span>}
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
                        Current organization
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
                        >
                            <IconCheck className="text-tertiary" />
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
                                <div className="ml-auto">
                                    <AccessLevelIndicator organization={currentOrganization} />
                                </div>
                            )}
                        </Link>
                    </DropdownMenuItem>
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
                        </>
                    )}
                    <Label intent="menu" className="px-2 mt-2">
                        Other organizations
                    </Label>
                    <DropdownMenuSeparator />
                    {otherOrganizations.map((otherOrganization) => (
                        <DropdownMenuItem asChild>
                            <ButtonPrimitive
                                menuItem
                                onClick={() => updateCurrentOrganization(otherOrganization.id)}
                                tooltip={`Switch to organization: ${otherOrganization.name}`}
                                tooltipPlacement="right"
                                data-attr="tree-navbar-organization-dropdown-other-organization-button"
                            >
                                <IconBlank />
                                <UploadedLogo
                                    size="xsmall"
                                    name={otherOrganization.name}
                                    entityId={otherOrganization.id}
                                    mediaId={otherOrganization.logo_media_id}
                                />
                                <span className="truncate max-w-full">{otherOrganization.name}</span>
                                <div className="ml-auto">
                                    <AccessLevelIndicator organization={otherOrganization} />
                                </div>
                            </ButtonPrimitive>
                        </DropdownMenuItem>
                    ))}
                    <DropdownMenuItem asChild>
                        {preflight?.can_create_org && (
                            <ButtonPrimitive
                                menuItem
                                data-attr="new-organization-button"
                                onClick={() =>
                                    guardAvailableFeature(
                                        AvailableFeature.ORGANIZATIONS_PROJECTS,
                                        () => {
                                            closeAccountPopover()
                                            showCreateOrganizationModal()
                                        },
                                        {
                                            guardOnCloud: false,
                                        }
                                    )
                                }
                                tooltip="Create a new organization"
                                tooltipPlacement="right"
                            >
                                <IconPlusSmall className="size-4" />
                                New organization
                            </ButtonPrimitive>
                        )}
                    </DropdownMenuItem>

                    <DropdownMenuSeparator />

                    <ThemeDropdown />

                    <DropdownMenuItem asChild>
                        <Link
                            to="https://posthog.com/changelog"
                            buttonProps={{
                                menuItem: true,
                            }}
                            onClick={(e) => {
                                e.preventDefault()
                                if (!mobileLayout) {
                                    e.preventDefault()
                                    openSidePanel(SidePanelTab.Docs, '/changelog')
                                }
                            }}
                            data-attr="whats-new-button"
                            target="_blank"
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
                        >
                            <IconFeatures />
                            Feature previews
                        </Link>
                    </DropdownMenuItem>
                    {user?.is_staff && (
                        <>
                            <DropdownMenuItem asChild>
                                <Link
                                    to="/admin/"
                                    buttonProps={{
                                        menuItem: true,
                                    }}
                                    tooltip="Django admin"
                                    tooltipPlacement="right"
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
