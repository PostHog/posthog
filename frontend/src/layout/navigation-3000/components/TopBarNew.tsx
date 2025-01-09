import './TopBar.scss'

import {
    IconCheckCircle,
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
import { LemonButton, LemonSnack, ProfilePicture } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
// import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { router } from 'kea-router'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { Link } from 'lib/lemon-ui/Link'
// import { AccountPopoverOverlay } from '~/layout/navigation/TopBar/AccountPopover'
// import { themeLogic } from '../themeLogic'
// import { TopBarNavButton } from './TopBarNavButton'
// import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
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
import { removeFlagIdIfPresent } from 'lib/utils/router-utils'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import React, { useMemo } from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { globalModalsLogic } from '~/layout/GlobalModals'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { AccessLevelIndicator } from '~/layout/navigation/OrganizationSwitcher'
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '~/lib/ui/Command/Command'
import { AvailableFeature, SidePanelTab, TeamBasicType } from '~/types'

import { sidePanelStateLogic } from '../sidepanel/sidePanelStateLogic'
import { themeLogic } from '../themeLogic'

/** Sync with --breadcrumbs-height-compact. */
export const BREADCRUMBS_HEIGHT_COMPACT = 44

function NavLink({
    children,
    to,
    active = false,
}: {
    children: React.ReactNode
    to: string
    active?: boolean
}): JSX.Element {
    return (
        <Link
            to={to}
            className={clsx(
                'text-sm text-text-primary px-2 py-1 rounded-md border border-text-primary hover:bg-text-primary hover:text-text-primary-inverted',
                active && 'bg-text-primary text-text-primary-inverted'
            )}
        >
            {children}
        </Link>
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
    // const { closeAccountPopover } = useActions(navigationLogic)

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

function OtherProjectButton({ team, disabled }: { team: TeamBasicType; disabled?: boolean }): JSX.Element {
    const { location } = useValues(router)

    const relativeOtherProjectPath = useMemo(() => {
        // NOTE: There is a tradeoff here - because we choose keep the whole path it could be that the
        // project switch lands on something like insight/abc that won't exist.
        // On the other hand, if we remove the ID, it could be that someone opens a page, realizes they're in the wrong project
        // and after switching is on a different page than before.
        let route = removeProjectIdIfPresent(location.pathname)
        route = removeFlagIdIfPresent(route)

        // List of routes that should redirect to project home
        // instead of keeping the current path.
        const redirectToHomeRoutes = ['/products', '/onboarding']

        const shouldRedirectToHome = redirectToHomeRoutes.some((redirectRoute) => route.includes(redirectRoute))

        if (shouldRedirectToHome) {
            return urls.project(team.id) // Go to project home
        }

        return urls.project(team.id, route)
    }, [location.pathname, team.id])

    return (
        <CommandItem
            key={team.name}
            value={team.name}
            disabled={disabled}
            asChild
            buttonProps={{
                to: relativeOtherProjectPath,
            }}
        >
            <ProjectName team={team} />
        </CommandItem>
    )
}

export function TopBarNew(): JSX.Element | null {
    // const { isAccountPopoverOpen, systemStatusHealthy } = useValues(navigationLogic)
    // const { closeAccountPopover, toggleAccountPopover } = useActions(navigationLogic)
    // const { theme } = useValues(themeLogic)
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

    // const { mobileLayout } = useValues(navigationLogic)
    // const { openSidePanel } = useActions(sidePanelStateLogic)
    // const { closeAccountPopover } = useActions(navigationLogic)
    // const { mobileLayout } = useValues(navigationLogic)
    // const { showNavOnMobile } = useActions(navigation3000Logic)
    // const { setActionsContainer } = useActions(breadcrumbsLogic)

    return (
        <div className="flex justify-between items-center gap-2 px-2 py-1 token-surface-3000-tertiary">
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
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
                        {currentOrganization?.name}
                    </Button>
                </DropdownMenuTrigger>
                {currentOrganization && (
                    <DropdownMenuContent side="bottom" align="start" className="min-w-56" loop>
                        <DropdownMenuLabel>Organizations</DropdownMenuLabel>
                        <DropdownMenuSub>
                            <DropdownMenuSubTrigger
                                buttonProps={
                                    {
                                        // hasIcon: true,
                                        // iconLeft: <IconCheckCircle className="size-4" />,
                                    }
                                }
                            >
                                {currentOrganization?.name}
                                <AccessLevelIndicator organization={currentOrganization} />
                            </DropdownMenuSubTrigger>
                            <DropdownMenuPortal>
                                <DropdownMenuSubContent loop>
                                    {currentOrganization && (
                                        <DropdownMenuItem
                                            disabled
                                            buttonProps={{
                                                tooltip: `This is your current organization`,
                                                tooltipPlacement: 'right',
                                            }}
                                        >
                                            {currentOrganization.name}
                                            <AccessLevelIndicator organization={currentOrganization} />
                                        </DropdownMenuItem>
                                    )}

                                    {otherOrganizations.map((otherOrganization) => (
                                        <>
                                            {/* <OtherOrganizationButton key={otherOrganization.id} organization={otherOrganization} index={i} /> */}
                                            <DropdownMenuItem
                                                key={otherOrganization.id}
                                                buttonProps={{
                                                    hasIcon: true,
                                                    iconLeft: (
                                                        <UploadedLogo
                                                            name={otherOrganization.name}
                                                            entityId={otherOrganization.id}
                                                            mediaId={otherOrganization.logo_media_id}
                                                        />
                                                    ),
                                                    tooltip: `Switch to organization ${otherOrganization.name}`,
                                                    tooltipPlacement: 'right',
                                                    onClick: () => updateUser({ theme_mode: 'light' }),
                                                }}
                                            >
                                                {otherOrganization.name}
                                            </DropdownMenuItem>
                                        </>
                                    ))}

                                    {/* {preflight?.can_create_org && (
                                        <DropdownMenuItem
                                            buttonProps={{
                                                hasIcon: true,
                                                onClick: () =>
                                                    guardAvailableFeature(
                                                        AvailableFeature.ORGANIZATIONS_PROJECTS,
                                                        () => {
                                                            showCreateOrganizationModal()
                                                        },
                                                        {
                                                            guardOnCloud: false,
                                                        }
                                                    ),
                                            }}
                                        >
                                            New organization
                                        </DropdownMenuItem>
                                    )} */}
                                </DropdownMenuSubContent>
                            </DropdownMenuPortal>
                        </DropdownMenuSub>

                        {preflight?.can_create_org && (
                            <DropdownMenuItem
                                buttonProps={{
                                    hasIcon: true,
                                    iconLeft: <IconPlus />,
                                    onClick: () =>
                                        guardAvailableFeature(
                                            AvailableFeature.ORGANIZATIONS_PROJECTS,
                                            () => {
                                                showCreateOrganizationModal()
                                            },
                                            {
                                                guardOnCloud: false,
                                            }
                                        ),
                                }}
                            >
                                New organization
                            </DropdownMenuItem>
                        )}

                        <DropdownMenuSeparator />

                        <DropdownMenuLabel>Projects for {currentOrganization?.name}</DropdownMenuLabel>

                        <DropdownMenuSub>
                            <DropdownMenuSubTrigger
                                buttonProps={{
                                    hasIcon: true,
                                    iconLeft: <IconCheckCircle className="size-4" />,
                                }}
                            >
                                <ProjectName team={currentTeam as TeamBasicType} />
                            </DropdownMenuSubTrigger>
                            <DropdownMenuSubContent loop>
                                <Command loop>
                                    <CommandInput
                                        placeholder="Search projects..."
                                        id="project-search"
                                        autoFocus={true}
                                    />
                                    <CommandList>
                                        <CommandEmpty>No projects found.</CommandEmpty>
                                        <CommandGroup>
                                            {currentOrganization.teams
                                                .sort((teamA, teamB) => teamA.name.localeCompare(teamB.name))
                                                .map((team) => (
                                                    // <CommandItem
                                                    //     key={team.name}
                                                    //     value={team.name}
                                                    //     onSelect={(value) => {
                                                    //         const selectedTeam = currentOrganization.teams.find((t) => t.name === value)
                                                    //         if (!selectedTeam) {
                                                    //             return
                                                    //         }
                                                    //         const route = removeProjectIdIfPresent(window.location.pathname)
                                                    //         const redirectToHomeRoutes = ['/products', '/onboarding']
                                                    //         const shouldRedirectToHome = redirectToHomeRoutes.some((r) => route.includes(r))
                                                    //         const path = shouldRedirectToHome ? urls.project(selectedTeam.id) : urls.project(selectedTeam.id, route)
                                                    //         router.actions.push(path)
                                                    //     }}
                                                    // >
                                                    //     <ProjectName team={team as TeamBasicType} />
                                                    // </CommandItem>
                                                    <OtherProjectButton
                                                        key={team.id}
                                                        team={team}
                                                        disabled={team.id === currentTeam?.id}
                                                    />
                                                ))}
                                        </CommandGroup>
                                    </CommandList>
                                </Command>
                            </DropdownMenuSubContent>
                        </DropdownMenuSub>

                        <DropdownMenuGroup>
                            <div className="hidden">
                                {/* Current project */}
                                <DropdownMenuItem
                                    buttonProps={{
                                        tooltip: 'This is your current project',
                                        tooltipPlacement: 'right',
                                        // TODO: Add side action to button
                                        // sideAction: {
                                        //     icon: <IconGear className="text-muted-alt" />,
                                        //     tooltip: `Go to ${currentTeam.name} settings`,
                                        //     onClick: () => {
                                        //         push(urls.settings('project'))
                                        //     },
                                        // },
                                    }}
                                >
                                    <ProjectName team={currentTeam as TeamBasicType} />
                                </DropdownMenuItem>

                                {/* Other projects */}
                                {/* {currentOrganization?.teams &&
                                    currentOrganization.teams
                                        .filter((team) => team.id !== currentTeam?.id)
                                        .sort((teamA, teamB) => teamA.name.localeCompare(teamB.name))
                                        .map((team) => <OtherProjectButton key={team.id} team={team} />)} */}
                            </div>

                            {/* New project */}
                            <DropdownMenuItem
                                data-attr="new-project-button"
                                buttonProps={{
                                    hasIcon: true,
                                    iconLeft: <IconPlus />,
                                    tooltip: 'Create a new project',
                                    tooltipPlacement: 'right',
                                    onClick: () =>
                                        guardAvailableFeature(
                                            AvailableFeature.ORGANIZATIONS_PROJECTS,
                                            () => {
                                                showCreateProjectModal()
                                            },
                                            {
                                                guardOnCloud: false,
                                            }
                                        ),
                                    // TODO: Add side action to button
                                    // sideAction: {
                                    //     icon: <IconGear className="text-muted-alt" />,
                                    //     tooltip: `Go to ${currentTeam.name} settings`,
                                    //     onClick: () => {
                                    //         push(urls.settings('project'))
                                    //     },
                                    // },
                                }}
                            >
                                New project
                            </DropdownMenuItem>
                        </DropdownMenuGroup>
                    </DropdownMenuContent>
                )}
            </DropdownMenu>

            <nav className="flex items-center gap-2">
                <NavLink to="/">Dashboards</NavLink>
                <NavLink to="/about">Notebooks</NavLink>
                <NavLink to="/contact">Data</NavLink>
                <NavLink to="/contact">People</NavLink>
                <NavLink to="/contact">Activity</NavLink>
                <NavLink to="/contact">Products</NavLink>
            </nav>

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
    )
}

// interface BreadcrumbProps {
//     breadcrumb: IBreadcrumb
//     here?: boolean
//     isOnboarding?: boolean
// }

// function Breadcrumb({ breadcrumb, here, isOnboarding }: BreadcrumbProps): JSX.Element {
//     const { renameState } = useValues(breadcrumbsLogic)
//     const { tentativelyRename, finishRenaming } = useActions(breadcrumbsLogic)
//     const [popoverShown, setPopoverShown] = useState(false)

//     const joinedKey = joinBreadcrumbKey(breadcrumb.key)

//     const breadcrumbName = isOnboarding && here ? 'Onboarding' : (breadcrumb.name as string)

//     let nameElement: JSX.Element
//     if (breadcrumb.symbol) {
//         nameElement = breadcrumb.symbol
//     } else if (breadcrumb.name != null && breadcrumb.onRename) {
//         nameElement = (
//             <EditableField
//                 name="item-name-small"
//                 value={renameState && renameState[0] === joinedKey ? renameState[1] : breadcrumbName}
//                 onChange={(newName) => tentativelyRename(joinedKey, newName)}
//                 onSave={(newName) => {
//                     void breadcrumb.onRename?.(newName)
//                 }}
//                 mode={renameState && renameState[0] === joinedKey ? 'edit' : 'view'}
//                 onModeToggle={(newMode) => {
//                     if (newMode === 'edit') {
//                         tentativelyRename(joinedKey, breadcrumbName)
//                     } else {
//                         finishRenaming()
//                     }
//                     setPopoverShown(false)
//                 }}
//                 placeholder="Unnamed"
//                 compactButtons="xsmall"
//                 editingIndication="underlined"
//             />
//         )
//     } else {
//         nameElement = (
//             <span className="flex items-center gap-1.5">
//                 {breadcrumbName || <i>Unnamed</i>}
//                 {'tag' in breadcrumb && breadcrumb.tag && <LemonTag size="small">{breadcrumb.tag}</LemonTag>}
//             </span>
//         )
//     }

//     const Component = breadcrumb.path ? Link : 'div'
//     const breadcrumbContent = (
//         <Component
//             className={clsx(
//                 'TopBar3000__breadcrumb',
//                 popoverShown && 'TopBar3000__breadcrumb--open',
//                 (breadcrumb.path || breadcrumb.popover) && 'TopBar3000__breadcrumb--actionable',
//                 here && 'TopBar3000__breadcrumb--here'
//             )}
//             onClick={() => {
//                 breadcrumb.popover && setPopoverShown(!popoverShown)
//             }}
//             data-attr={`breadcrumb-${joinedKey}`}
//             to={breadcrumb.path}
//         >
//             {nameElement}
//             {breadcrumb.popover && !breadcrumb.symbol && <IconChevronDown />}
//         </Component>
//     )

//     if (breadcrumb.popover) {
//         return (
//             <Popover
//                 {...breadcrumb.popover}
//                 visible={popoverShown}
//                 onClickOutside={() => {
//                     if (popoverShown) {
//                         setPopoverShown(false)
//                     }
//                 }}
//                 onClickInside={() => {
//                     if (popoverShown) {
//                         setPopoverShown(false)
//                     }
//                 }}
//             >
//                 {breadcrumbContent}
//             </Popover>
//         )
//     }

//     return breadcrumbContent
// }

// interface HereProps {
//     breadcrumb: IBreadcrumb
//     isOnboarding?: boolean
// }

// function Here({ breadcrumb, isOnboarding }: HereProps): JSX.Element {
//     const { renameState } = useValues(breadcrumbsLogic)
//     const { tentativelyRename, finishRenaming } = useActions(breadcrumbsLogic)

//     const joinedKey = joinBreadcrumbKey(breadcrumb.key)
//     const hereName = isOnboarding ? 'Onboarding' : (breadcrumb.name as string)

//     return (
//         <h1 className="TopBar3000__here" data-attr="top-bar-name">
//             {breadcrumb.name == null ? (
//                 <LemonSkeleton className="w-40 h-4" />
//             ) : breadcrumb.onRename ? (
//                 <EditableField
//                     name="item-name-large"
//                     value={renameState && renameState[0] === joinedKey ? renameState[1] : hereName}
//                     onChange={(newName) => {
//                         tentativelyRename(joinedKey, newName)
//                         if (breadcrumb.forceEditMode) {
//                             // In this case there's no "Save" button, we update on input
//                             void breadcrumb.onRename?.(newName)
//                         }
//                     }}
//                     onSave={(newName) => {
//                         void breadcrumb.onRename?.(newName)
//                     }}
//                     mode={breadcrumb.forceEditMode || (renameState && renameState[0] === joinedKey) ? 'edit' : 'view'}
//                     onModeToggle={
//                         !breadcrumb.forceEditMode
//                             ? (newMode) => {
//                                 if (newMode === 'edit') {
//                                     tentativelyRename(joinedKey, hereName)
//                                 } else {
//                                     finishRenaming()
//                                 }
//                             }
//                             : undefined
//                     }
//                     placeholder="Unnamed"
//                     compactButtons="xsmall"
//                     editingIndication="underlined"
//                     autoFocus
//                 />
//             ) : (
//                 <span>{hereName}</span>
//             )}
//         </h1>
//     )
// }

// function joinBreadcrumbKey(key: IBreadcrumb['key']): string {
//     return Array.isArray(key) ? key.map(String).join(':') : String(key)
// }
