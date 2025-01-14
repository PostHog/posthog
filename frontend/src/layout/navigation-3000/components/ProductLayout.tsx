import './TopBar.scss'

import {
    IconChevronDown,
    IconConfetti,
    IconDay,
    IconFeatures,
    IconLaptop,
    IconLeave,
    IconLive,
    IconNight,
    IconPalette,
    IconPlus,
    IconReceipt,
    IconSearch,
    IconServer,
    IconShieldLock,
} from '@posthog/icons'
import { LemonBadge, LemonButton, LemonSnack, LemonTabs, ProfilePicture } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo'
import { Button } from 'lib/ui/Button/Button'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuPortal,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from 'lib/ui/Dropdown/Dropdown'
import DropdownGen from 'lib/ui/Dropdown/DropdownGen'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { globalModalsLogic } from '~/layout/GlobalModals'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { AccessLevelIndicator } from '~/layout/navigation/OrganizationSwitcher'
import { ProductLayoutTopbarTab } from '~/layout/navigation/TopBar/productLayoutLogic'
import { AvailableFeature, SidePanelTab, TeamBasicType } from '~/types'

import { navigation3000Logic } from '../navigationLogic'
import { sidePanelStateLogic } from '../sidepanel/sidePanelStateLogic'
import { themeLogic } from '../themeLogic'

function TopBarNavButton({
    to,
    title,
    identifier,
    active,
}: {
    to: string
    title?: string
    identifier: string
    active: boolean
}): JSX.Element {
    const { sceneBreadcrumbKeys } = useValues(breadcrumbsLogic)
    const { activeScene } = useValues(sceneLogic)

    // console.log('activeTopBarNavItemId', activeNavbarItemId, identifier)
    const here = activeScene === identifier || sceneBreadcrumbKeys.includes(identifier)

    return (
        <Button to={to} active={active || here} intent="top-bar-tabs">
            {title}
        </Button>
    )
}

function ProjectName({ team }: { team: TeamBasicType }): JSX.Element {
    return (
        <>
            <span>{team.name}</span>
            {team.is_demo ? <LemonSnack className="ml-2 text-xs shrink-0">Demo</LemonSnack> : null}
        </>
    )
}

function NavAccountItem(): JSX.Element {
    const { user } = useValues(userLogic)

    return (
        <div className="flex items-center gap-2 text-left">
            <ProfilePicture user={user} size="xl" />
            <div className="flex flex-col">
                <div className="token-content-primary font-semibold mb-1 text-sm text-truncate text-capitalize">
                    {user?.first_name}
                </div>
                <div
                    className="token-content-tertiary overflow-hidden truncate text-xs text-capitalize"
                    title={user?.email}
                >
                    {user?.email}
                </div>
            </div>
        </div>
    )
}

// function OtherProjectButton({ team, disabled }: { team: TeamBasicType; disabled?: boolean }): JSX.Element {
//     const { location } = useValues(router)

//     const relativeOtherProjectPath = useMemo(() => {
//         // NOTE: There is a tradeoff here - because we choose keep the whole path it could be that the
//         // project switch lands on something like insight/abc that won't exist.
//         // On the other hand, if we remove the ID, it could be that someone opens a page, realizes they're in the wrong project
//         // and after switching is on a different page than before.
//         let route = removeProjectIdIfPresent(location.pathname)
//         route = removeFlagIdIfPresent(route)

//         // List of routes that should redirect to project home
//         // instead of keeping the current path.
//         const redirectToHomeRoutes = ['/products', '/onboarding']

//         const shouldRedirectToHome = redirectToHomeRoutes.some((redirectRoute) => route.includes(redirectRoute))

//         if (shouldRedirectToHome) {
//             return urls.project(team.id) // Go to project home
//         }

//         return urls.project(team.id, route)
//     }, [location.pathname, team.id])

//     return (
//         <CommandItem
//             key={team.name}
//             value={team.name}
//             disabled={disabled}
//             asChild
//             buttonProps={{
//                 to: relativeOtherProjectPath,
//             }}
//         >
//             <ProjectName team={team} />
//         </CommandItem>
//     )
// }

function TopBarTabs(): JSX.Element {
    // const { productLayoutTabs } = useValues(productLayoutLogic)
    const { productLayoutTabs } = useValues(breadcrumbsLogic)
    if (!productLayoutTabs || productLayoutTabs.length === 0) {
        return <></>
    }

    const lemonTabs = productLayoutTabs.map((tab: ProductLayoutTopbarTab) => ({
        key: tab.key,
        label: (
            <>
                {tab.label}
                {tab.isNew && <LemonBadge className="ml-1" size="small" />}
            </>
        ),
        content: tab.content,
    }))

    return (
        <LemonTabs
            activeKey={productLayoutTabs[0].key}
            onChange={(newKey) => {
                // setActiveTab(newKey)
                router.actions.push(
                    productLayoutTabs.find((tab: ProductLayoutTopbarTab) => tab.key === newKey)?.url || ''
                )
                // if (tabs.find((tab) => tab.key === newKey)?.removeNewWhenVisited) {
                //     hideNewBadge()
                // }
            }}
            tabs={lemonTabs}
        />
    )
}

export function TopNav(): JSX.Element {
    const { preflight, isCloudOrDev, isCloud } = useValues(preflightLogic)
    const { user, themeMode } = useValues(userLogic)
    const { updateUser, logout } = useActions(userLogic)
    const { customCssEnabled } = useValues(themeLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { mobileLayout } = useValues(navigationLogic)
    const { currentOrganization, otherOrganizations } = useValues(breadcrumbsLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { showCreateOrganizationModal, showCreateProjectModal } = useActions(globalModalsLogic)
    const { currentTeam } = useValues(teamLogic)
    const { topBarNavbarItems, activeNavbarItemId } = useValues(navigation3000Logic)

    return (
        <>
            <div className="h-[42px] flex justify-between items-center gap-2 px-2 token-surface-3000-tertiary">
                <DropdownGen
                    id="organization-team-dropdown"
                    align="start"
                    alignOffset={0}
                    trigger={
                        <Button
                            intent="muted-darker"
                            aria-label="Account"
                            hasIcon
                            iconRight={<IconChevronDown />}
                            iconLeft={
                                <UploadedLogo
                                    name={currentOrganization?.name || ''}
                                    entityId={currentOrganization?.id || ''}
                                    mediaId={currentOrganization?.logo_media_id || ''}
                                />
                            }
                        >
                            {currentOrganization?.name} / {currentTeam?.name}
                        </Button>
                    }
                    items={[
                        {
                            trigger: (
                                <>
                                    {currentOrganization?.name}
                                    {currentOrganization && <AccessLevelIndicator organization={currentOrganization} />}
                                </>
                            ),
                            label: 'Current Organization',
                            dropdownItems: [
                                {
                                    label: 'Organizations',
                                    type: 'label',
                                },
                                {
                                    trigger: (
                                        <>
                                            {currentOrganization?.name}
                                            {currentOrganization && (
                                                <AccessLevelIndicator organization={currentOrganization} />
                                            )}
                                        </>
                                    ),
                                    buttonProps: {
                                        disabled: true,
                                        hasIcon: true,
                                        iconLeft: (
                                            <UploadedLogo
                                                name={currentOrganization?.name || ''}
                                                entityId={currentOrganization?.id || ''}
                                                mediaId={currentOrganization?.logo_media_id || ''}
                                            />
                                        ),
                                    },
                                },
                                ...otherOrganizations.map((org) => ({
                                    trigger: org.name,
                                    buttonProps: {
                                        hasIcon: true,
                                        iconLeft: (
                                            <UploadedLogo
                                                name={org.name}
                                                entityId={org.id}
                                                mediaId={org.logo_media_id}
                                            />
                                        ),
                                        tooltip: `Switch to organization ${org.name}`,
                                        tooltipPlacement: 'right' as const, // Type assertion to fix placement error
                                    },
                                    onClick: () => updateUser({ theme_mode: 'light' }),
                                })),
                            ],
                        },
                        ...(preflight?.can_create_org
                            ? [
                                  {
                                      trigger: 'New organization',
                                      buttonProps: {
                                          hasIcon: true,
                                          iconLeft: <IconPlus />,
                                          tooltip: 'Create a new organization',
                                          tooltipPlacement: 'right' as const,
                                      },
                                      onClick: () =>
                                          guardAvailableFeature(
                                              AvailableFeature.ORGANIZATIONS_PROJECTS,
                                              showCreateOrganizationModal,
                                              { guardOnCloud: false }
                                          ),
                                  },
                              ]
                            : []),
                        {
                            type: 'divider',
                        },
                        {
                            type: 'combobox',
                            trigger: <ProjectName team={currentTeam as TeamBasicType} />,
                            commandProps: {
                                placeholder: 'Search projects...',
                                autoFocus: true,
                                emptyState: 'No projects found.',
                            },
                            label: `Current Project`,
                            dropdownItems: [
                                ...(currentOrganization?.teams ?? [])
                                    .sort((teamA, teamB) => teamA.name.localeCompare(teamB.name))
                                    .map((team) => ({
                                        trigger: <ProjectName team={team} />,
                                        buttonProps: {
                                            disabled: team.id === currentTeam?.id,
                                            tooltip:
                                                team.id === currentTeam?.id ? 'Current project' : 'Switch to project',
                                            tooltipPlacement: 'right' as const,
                                        },
                                        onClick: () => {
                                            // Project switching logic
                                        },
                                    })),
                            ],
                        },

                        {
                            trigger: 'New project',
                            buttonProps: {
                                hasIcon: true,
                                iconLeft: <IconPlus />,
                                tooltip: 'Create a new project',
                                tooltipPlacement: 'right' as const,
                            },
                            onClick: () =>
                                guardAvailableFeature(AvailableFeature.ORGANIZATIONS_PROJECTS, showCreateProjectModal, {
                                    guardOnCloud: false,
                                }),
                        },
                    ]}
                />

                <ul className="flex gap-2 self-end">
                    {topBarNavbarItems.map((item) => (
                        <li className="relative top-[1px]" key={item.identifier}>
                            <TopBarNavButton
                                title={item.label}
                                to={'to' in item ? String(item.to) : ''}
                                identifier={item.identifier}
                                active={activeNavbarItemId === item.identifier}
                            />
                        </li>
                    ))}
                </ul>

                <div className="flex gap-2">
                    <LemonButton size="small">
                        <IconSearch />
                    </LemonButton>
                    {/* <Popover
                        overlay={<AccountPopoverOverlay />}
                        visible={isAccountPopoverOpen}
                        onClickOutside={closeAccountPopover}
                        placement="bottom-start"
                
                    >
                        <TopBarNavButton
                            identifier="me"
                            // title={`Hi${user?.first_name ? `, ${user?.first_name}` : ''}!`}
                            // shortTitle={user?.first_name || user?.email}
                            onClick={toggleAccountPopover}
                        >
                            {`Hi${user?.first_name ? `, ${user?.first_name}` : ''}!`}
                        </TopBarNavButton>
                    </Popover> */}

                    <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                            {}
                            <Button
                                intent="muted-darker"
                                aria-label="Account"
                                hasIcon
                                iconRight={<IconChevronDown />}
                                iconLeft={<ProfilePicture user={user} size="md" />}
                            >
                                {user?.first_name}
                            </Button>
                        </DropdownMenuTrigger>

                        <DropdownMenuContent side="bottom" align="end" className="min-w-56" loop>
                            <DropdownMenuLabel>Sign in as</DropdownMenuLabel>

                            <DropdownMenuGroup>
                                <DropdownMenuItem
                                    buttonProps={{
                                        hasIcon: true,
                                        to: urls.settings('user'),
                                        tooltip: 'Sign in as',
                                        tooltipPlacement: 'left',
                                    }}
                                >
                                    <NavAccountItem />
                                </DropdownMenuItem>

                                <DropdownMenuSeparator />

                                <DropdownMenuLabel>Current organization</DropdownMenuLabel>

                                {currentOrganization ? (
                                    <DropdownMenuItem
                                        buttonProps={{
                                            hasIcon: true,
                                            to: urls.settings('user'),
                                            tooltip: 'Organization settings',
                                            tooltipPlacement: 'left',
                                            iconLeft: (
                                                <UploadedLogo
                                                    name={currentOrganization.name}
                                                    entityId={currentOrganization.id}
                                                    mediaId={currentOrganization.logo_media_id}
                                                />
                                            ),
                                        }}
                                    >
                                        <div className="flex self-end">
                                            <span className="font-medium">{currentOrganization.name}</span>
                                            <AccessLevelIndicator organization={currentOrganization} />
                                        </div>
                                    </DropdownMenuItem>
                                ) : null}

                                {isCloudOrDev ? (
                                    <DropdownMenuItem
                                        buttonProps={{
                                            hasIcon: true,
                                            to: urls.organizationBilling(),
                                            iconLeft: <IconReceipt />,
                                        }}
                                    >
                                        Billing
                                    </DropdownMenuItem>
                                ) : null}

                                <DropdownMenuSeparator />

                                <DropdownMenuSub>
                                    <DropdownMenuSubTrigger buttonProps={{ hasIcon: true, iconLeft: <IconPalette /> }}>
                                        Color theme
                                        <span className="font-normal text-xs">{themeMode} mode</span>
                                    </DropdownMenuSubTrigger>
                                    <DropdownMenuPortal>
                                        <DropdownMenuSubContent loop>
                                            <DropdownMenuItem
                                                buttonProps={{
                                                    hasIcon: true,
                                                    iconLeft: <IconDay />,
                                                    onClick: () => updateUser({ theme_mode: 'light' }),
                                                }}
                                            >
                                                Light mode
                                            </DropdownMenuItem>
                                            <DropdownMenuItem
                                                buttonProps={{
                                                    hasIcon: true,
                                                    iconLeft: <IconNight />,
                                                    onClick: () => updateUser({ theme_mode: 'dark' }),
                                                }}
                                            >
                                                Dark mode
                                            </DropdownMenuItem>
                                            <DropdownMenuItem
                                                buttonProps={{
                                                    hasIcon: true,
                                                    iconLeft: <IconLaptop />,
                                                    onClick: () => updateUser({ theme_mode: 'system' }),
                                                }}
                                            >
                                                Sync with system
                                            </DropdownMenuItem>
                                            {customCssEnabled && (
                                                <DropdownMenuItem
                                                    buttonProps={{
                                                        hasIcon: true,
                                                        iconLeft: <IconPalette />,
                                                        onClick: () => router.actions.push(urls.customCss()),
                                                    }}
                                                >
                                                    Edit custom CSS
                                                </DropdownMenuItem>
                                            )}
                                        </DropdownMenuSubContent>
                                    </DropdownMenuPortal>
                                </DropdownMenuSub>

                                <DropdownMenuItem
                                    buttonProps={{
                                        hasIcon: true,
                                        iconLeft: <IconLive />,
                                        // TODO: Add this back in when i do mobile layout
                                        // to: 'https://posthog.com/changelog',
                                        onClick: (e) => {
                                            if (!mobileLayout) {
                                                e.preventDefault()
                                                openSidePanel(SidePanelTab.Docs, '/changelog')
                                            }
                                        },
                                    }}
                                >
                                    What's new?
                                </DropdownMenuItem>
                                <DropdownMenuItem
                                    buttonProps={{
                                        hasIcon: true,
                                        iconLeft: <IconFeatures />,
                                        // TODO: link to page for mobile layout like "whats new"?
                                        onClick: () => {
                                            openSidePanel(SidePanelTab.FeaturePreviews)
                                        },
                                    }}
                                >
                                    Feature previews
                                </DropdownMenuItem>

                                {user?.is_staff && (
                                    <>
                                        <DropdownMenuSeparator />
                                        <DropdownMenuItem
                                            data-attr="top-menu-django-admin"
                                            buttonProps={{
                                                hasIcon: true,
                                                iconLeft: <IconShieldLock />,
                                                to: '/admin/',
                                                disableClientSideRouting: true,
                                            }}
                                        >
                                            Django admin
                                        </DropdownMenuItem>

                                        <DropdownMenuItem
                                            data-attr="top-menu-instance-panel"
                                            buttonProps={{
                                                hasIcon: true,
                                                iconLeft: <IconServer />,
                                                to: urls.instanceStatus(),
                                                disableClientSideRouting: true,
                                                // TODO: add side action to button
                                                // sideAction={{
                                                //     tooltip: 'Async migrations',
                                                //     tooltipPlacement: 'right',
                                                //     icon: <IconCheckCircle />,
                                                //     to: urls.asyncMigrations(),
                                                //     onClick: closeAccountPopover,
                                                // }}
                                            }}
                                        >
                                            Instance panel
                                        </DropdownMenuItem>
                                    </>
                                )}

                                <DropdownMenuSeparator />

                                {!isCloud && (
                                    <DropdownMenuItem
                                        data-attr="top-menu-upgrade-to-cloud"
                                        buttonProps={{
                                            hasIcon: true,
                                            iconLeft: <IconConfetti />,
                                            to: urls.moveToPostHogCloud(),
                                        }}
                                    >
                                        Try PostHog Cloud
                                    </DropdownMenuItem>
                                )}

                                <DropdownMenuSeparator />

                                <DropdownMenuItem
                                    buttonProps={{
                                        hasIcon: true,
                                        iconLeft: <IconLeave />,
                                        onClick: () => {
                                            logout()
                                        },
                                    }}
                                >
                                    Log out
                                </DropdownMenuItem>
                            </DropdownMenuGroup>
                        </DropdownMenuContent>
                    </DropdownMenu>
                </div>
            </div>
            <div className="relative z-[3] flex justify-center items-center h-[34px] border-t token-surface-3000-secondary token-border-3000-secondary">
                <TopBarTabs />
            </div>
        </>
    )
}
// interface ProductLayoutProps extends PropsWithChildren<any> {}

export function ProductLayout(): JSX.Element | null {
    return (
        <>
            <TopNav />
            {/* <div className="grid grid-cols-[250px_1fr]">
                <ul>
                    <li>
                        <Link to="/">Home</Link>
                    </li>
                </ul>
                <div className="p-4">{children}</div>
            </div> */}
        </>
    )
}
