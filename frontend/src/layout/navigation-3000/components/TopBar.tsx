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
    IconReceipt,
    IconSearch,
    IconServer,
    IconShieldLock,
} from '@posthog/icons'
import { LemonButton, ProfilePicture } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
// import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { router } from 'kea-router'
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
import React from 'react'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { AccessLevelIndicator } from '~/layout/navigation/OrganizationSwitcher'
import { SidePanelTab } from '~/types'

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

export function TopBar(): JSX.Element | null {
    // const { isAccountPopoverOpen, systemStatusHealthy } = useValues(navigationLogic)
    // const { closeAccountPopover, toggleAccountPopover } = useActions(navigationLogic)
    // const { theme } = useValues(themeLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { isCloudOrDev, isCloud } = useValues(preflightLogic)
    const { user, themeMode } = useValues(userLogic)
    const { updateUser, logout } = useActions(userLogic)
    const { customCssEnabled } = useValues(themeLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { mobileLayout } = useValues(navigationLogic)

    // const { mobileLayout } = useValues(navigationLogic)
    // const { openSidePanel } = useActions(sidePanelStateLogic)
    // const { preflight, isCloudOrDev, isCloud } = useValues(preflightLogic)
    // const { closeAccountPopover } = useActions(navigationLogic)
    // const { mobileLayout } = useValues(navigationLogic)
    // const { showNavOnMobile } = useActions(navigation3000Logic)
    // const { breadcrumbs, renameState } = useValues(breadcrumbsLogic)
    // const { setActionsContainer } = useActions(breadcrumbsLogic)

    // const [compactionRate, setCompactionRate] = useState(0)

    // // Always show in full on mobile, as there we are very constrained in width, but not so much height
    // const effectiveCompactionRate = mobileLayout ? 0 : compactionRate
    // const isOnboarding = router.values.location.pathname.includes('/onboarding/')

    // useLayoutEffect(() => {
    //     function handleScroll(): void {
    //         const mainElement = document.getElementsByTagName('main')[0]
    //         const mainScrollTop = mainElement.scrollTop
    //         const compactionDistance = Math.min(
    //             // This ensures that scrolling to the bottom of the scene will always result in the compact top bar state
    //             // even if there's just a few pixels of scroll room. Otherwise, the top bar would be halfway-compact then
    //             mainElement.scrollHeight - mainElement.clientHeight,
    //             BREADCRUMBS_HEIGHT_COMPACT
    //         )
    //         const newCompactionRate = compactionDistance > 0 ? Math.min(mainScrollTop / compactionDistance, 1) : 0
    //         setCompactionRate(newCompactionRate)
    //         if (
    //             renameState &&
    //             ((newCompactionRate > 0.5 && compactionRate <= 0.5) ||
    //                 (newCompactionRate <= 0.5 && compactionRate > 0.5))
    //         ) {
    //             // Transfer selection from the outgoing input to the incoming one
    //             const [source, target] = newCompactionRate > 0.5 ? ['large', 'small'] : ['small', 'large']
    //             const sourceEl = document.querySelector<HTMLInputElement>(`input[name="item-name-${source}"]`)
    //             const targetEl = document.querySelector<HTMLInputElement>(`input[name="item-name-${target}"]`)
    //             if (sourceEl && targetEl) {
    //                 targetEl.focus()
    //                 targetEl.setSelectionRange(sourceEl.selectionStart || 0, sourceEl.selectionEnd || 0)
    //             }
    //         }
    //     }
    //     const main = document.getElementsByTagName('main')[0]
    //     main.addEventListener('scroll', handleScroll)
    //     return () => main.removeEventListener('scroll', handleScroll)
    // }, [compactionRate])

    // return breadcrumbs.length ? (
    //     <div
    //         className={clsx(
    //             'TopBar3000',
    //             effectiveCompactionRate === 0 && 'TopBar3000--full',
    //             effectiveCompactionRate === 1 && 'TopBar3000--compact'
    //         )}
    //         // eslint-disable-next-line react/forbid-dom-props
    //         style={{ '--breadcrumbs-compaction-rate': effectiveCompactionRate } as React.CSSProperties}
    //     >
    //         <div className="TopBar3000__content">
    //             {mobileLayout && (
    //                 <LemonButton
    //                     size="small"
    //                     onClick={() => showNavOnMobile()}
    //                     icon={<IconMenu />}
    //                     className="TopBar3000__hamburger"
    //                 />
    //             )}
    //             <div className="TopBar3000__breadcrumbs">
    //                 {breadcrumbs.length > 1 && (
    //                     <div className="TopBar3000__trail">
    //                         {breadcrumbs.slice(0, -1).map((breadcrumb) => (
    //                             <React.Fragment key={joinBreadcrumbKey(breadcrumb.key)}>
    //                                 <Breadcrumb breadcrumb={breadcrumb} />
    //                                 <div className="TopBar3000__separator" />
    //                             </React.Fragment>
    //                         ))}
    //                         <Breadcrumb
    //                             breadcrumb={breadcrumbs[breadcrumbs.length - 1]}
    //                             here
    //                             isOnboarding={isOnboarding}
    //                         />
    //                     </div>
    //                 )}
    //                 <Here breadcrumb={breadcrumbs[breadcrumbs.length - 1]} isOnboarding={isOnboarding} />
    //             </div>
    //             <FlaggedFeature flag="metalytics">
    //                 <div className="shrink-1">
    //                     <MetalyticsSummary />
    //                 </div>
    //             </FlaggedFeature>
    //             <div className="TopBar3000__actions border-danger" ref={setActionsContainer} />
    //         </div>
    //     </div>
    // ) : null
    return (
        <div className="flex justify-between items-center gap-2 px-2 py-1 token-surface-3000-tertiary">
            <LemonButton size="small">Posthog App + Website</LemonButton>

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
                        {/* eslint-disable-next-line posthog/warn-elements */}
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
