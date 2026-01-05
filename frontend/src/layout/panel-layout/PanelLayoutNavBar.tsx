import { Tooltip } from '@base-ui/react/tooltip'
import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useRef, useState } from 'react'

import {
    IconApps,
    IconChevronRight,
    IconClock,
    IconDatabase,
    IconFolderOpen,
    IconGear,
    IconHome,
    IconNewspaper,
    IconPeople,
    IconSearch,
    IconShortcut,
    IconSidebarClose,
    IconSidebarOpen,
    IconToolbar,
} from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { AccountMenu } from 'lib/components/Account/AccountMenu'
import { AppShortcut } from 'lib/components/AppShortcuts/AppShortcut'
import { DebugNotice } from 'lib/components/DebugNotice'
import { NavPanelAdvertisement } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisement'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { FEATURE_FLAGS } from 'lib/constants'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    ContextMenu,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuTrigger,
} from 'lib/ui/ContextMenu/ContextMenu'
import { ListBox } from 'lib/ui/ListBox/ListBox'
import { TooltipPayload } from 'lib/ui/Tooltip/GlobalTooltip'
import { tooltipHandle } from 'lib/ui/Tooltip/GlobalTooltip'
import { cn } from 'lib/utils/css-classes'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { newTabSceneLogic } from 'scenes/new-tab/newTabSceneLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { PinnedFolder } from '~/layout/panel-layout/PinnedFolder/PinnedFolder'
import { BrowserLikeMenuItems } from '~/layout/panel-layout/ProjectTree/menus/BrowserLikeMenuItems'
import { PanelLayoutNavIdentifier, panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { ConfigurePinnedTabsModal } from '~/layout/scenes/ConfigurePinnedTabsModal'
import { SidePanelTab } from '~/types'

import { OrganizationMenu } from '../../lib/components/Account/OrganizationMenu'
import { ProjectMenu } from '../../lib/components/Account/ProjectMenu'
import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { SidePanelActivationIcon } from '../navigation-3000/sidepanel/panels/activation/SidePanelActivation'
import { sidePanelLogic } from '../navigation-3000/sidepanel/sidePanelLogic'
import { sidePanelStateLogic } from '../navigation-3000/sidepanel/sidePanelStateLogic'
import { RecentItemsMenu } from './ProjectTree/menus/RecentItemsMenu'

const navBarStyles = cva({
    base: 'flex flex-col max-h-screen min-h-screen bg-surface-tertiary z-[var(--z-layout-navbar)] relative border-r border-r-transparent',
    variants: {
        isLayoutNavCollapsed: {
            true: 'w-[var(--project-navbar-width-collapsed)]',
            false: 'w-[var(--project-navbar-width)]',
        },
        isMobileLayout: {
            true: 'absolute top-0 bottom-0 left-0',
            false: '',
        },
    },
})

export function PanelLayoutNavBar({ children }: { children: React.ReactNode }): JSX.Element {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const [isConfigurePinnedTabsOpen, setIsConfigurePinnedTabsOpen] = useState(false)
    const {
        showLayoutPanel,
        setActivePanelIdentifier,
        clearActivePanelIdentifier,
        toggleLayoutNavCollapsed,
        showLayoutNavBar,
        resetPanelLayout,
    } = useActions(panelLayoutLogic)
    const {
        pathname,
        isLayoutPanelVisible,
        activePanelIdentifier,
        activePanelIdentifierFromUrl,
        mainContentRef,
        isLayoutPanelPinned,
        isLayoutNavCollapsed,
        isLayoutNavbarVisible,
    } = useValues(panelLayoutLogic)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { user } = useValues(userLogic)
    const { visibleTabs, sidePanelOpen, selectedTab } = useValues(sidePanelLogic)
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)
    const { firstTabIsActive, activeTabId } = useValues(sceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    function handlePanelTriggerClick(item: PanelLayoutNavIdentifier): void {
        if (activePanelIdentifier !== item) {
            setActivePanelIdentifier(item)
            showLayoutPanel(true)
        } else if (activePanelIdentifier === item) {
            clearActivePanelIdentifier()
            showLayoutPanel(false)
        }
    }

    function handleStaticNavbarItemClick(to?: string, isKeyboardAction = false): void {
        if (!isLayoutPanelPinned) {
            clearActivePanelIdentifier()
            showLayoutPanel(false)
        }

        if (isKeyboardAction) {
            mainContentRef?.current?.focus()
        }
        if (isMobileLayout && isLayoutNavbarVisible) {
            showLayoutNavBar(false)
        }
        if (to) {
            router.actions.push(to)
        }
    }

    const isStaticNavItemActive = (itemIdentifier: string): boolean => {
        const currentPath = removeProjectIdIfPresent(pathname)

        if (itemIdentifier === 'Home' && currentPath === '/') {
            return true
        }
        if (itemIdentifier === 'Feed' && currentPath === '/feed') {
            return true
        }
        if (itemIdentifier === 'Activity' && currentPath.startsWith('/activity/')) {
            return true
        }
        if (itemIdentifier === 'Settings' && currentPath.startsWith('/settings/')) {
            return true
        }
        if (itemIdentifier === 'Toolbar' && currentPath === '/toolbar') {
            return true
        }

        return false
    }

    function handleSearchClick(): void {
        const mountedLogic = activeTabId ? newTabSceneLogic.findMounted({ tabId: activeTabId }) : null

        if (mountedLogic) {
            setTimeout(() => {
                mountedLogic.actions.triggerSearchPulse()
            }, 100)
        }
    }

    const navItems: {
        identifier: string
        label: string
        icon: React.ReactNode
        showChevron?: boolean
        to?: string
        onClick?: (e?: React.KeyboardEvent) => void
        tooltip?: Pick<TooltipPayload, 'title' | 'content'>
        documentationUrl?: string
    }[] = [
        {
            identifier: 'ProjectHomepage',
            label: 'Home',
            icon: <IconHome />,
            to: urls.projectRoot(),
            onClick: () => handleStaticNavbarItemClick(urls.projectRoot(), true),
            tooltip: {
                title: 'Home',
                content: 'Customize what you see when you open the app',
            },
        },
        {
            identifier: 'Search',
            label: 'Search',
            icon: <IconSearch />,
            to: urls.newTab(),
            onClick: () => {
                handleSearchClick()
                handleStaticNavbarItemClick(urls.newTab(), true)
            },
            tooltip: {
                title: 'Search',
                content: 'Search for apps, events, properties, and more',
            },
        },
        ...(featureFlags[FEATURE_FLAGS.HOME_FEED_TAB]
            ? [
                  {
                      identifier: 'ProjectFeed',
                      label: 'Feed',
                      icon: <IconNewspaper />,
                      to: urls.feed(),
                      onClick: () => handleStaticNavbarItemClick(urls.feed(), true),
                      tooltip: {
                          title: 'Feed',
                          content: 'Stay updated with recent activities and changes in your project',
                      },
                  },
              ]
            : []),
        {
            identifier: 'Activity',
            label: 'Activity',
            icon: <IconClock />,
            to: urls.activity(),
            onClick: () => handleStaticNavbarItemClick(urls.activity(), true),
            tooltip: {
                title: 'Activity',
                content: 'View event details, sessions and live feed of events',
            },
            documentationUrl: 'https://posthog.com/docs/data/events',
        },
        ...(featureFlags[FEATURE_FLAGS.CUSTOM_PRODUCTS_SIDEBAR] === 'test'
            ? []
            : [
                  {
                      identifier: 'Products',
                      label: 'All apps',
                      icon: <IconApps />,
                      onClick: (e?: React.KeyboardEvent) => {
                          if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                              handlePanelTriggerClick('Products')
                          }
                      },
                      showChevron: true,
                      tooltip: {
                          title: 'All apps',
                          content: 'View all apps in your project',
                      },
                  },
              ]),
        {
            identifier: 'DataManagement',
            label: 'Data management',
            icon: <IconDatabase />,
            onClick: (e?: React.KeyboardEvent) => {
                if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                    handlePanelTriggerClick('DataManagement')
                }
            },
            showChevron: true,
            tooltip: {
                title: 'Data management',
                content: 'Manage your data, including events, properties, and more',
            },
            documentationUrl: 'https://posthog.com/docs/data',
        },
        {
            identifier: 'People',
            label: 'People & groups',
            icon: <IconPeople />,
            onClick: (e?: React.KeyboardEvent) => {
                if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                    handlePanelTriggerClick('People')
                }
            },
            showChevron: true,
            tooltip: {
                title: 'People & groups',
                content: 'View and manage people and groups in your project',
            },
            documentationUrl: 'https://posthog.com/docs/data/persons',
        },
        {
            identifier: 'Shortcuts',
            label: 'Shortcuts',
            icon: <IconShortcut />,
            onClick: (e?: React.KeyboardEvent) => {
                if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                    handlePanelTriggerClick('Shortcuts')
                }
            },
            showChevron: true,
            tooltip: {
                title: 'Shortcuts',
                content: 'Access your favorite shortcuts quickly',
            },
        },
        {
            identifier: 'Project',
            label: 'Project',
            icon: <IconFolderOpen className="stroke-[1.2]" />,
            onClick: (e?: React.KeyboardEvent) => {
                if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                    handlePanelTriggerClick('Project')
                }
            },
            showChevron: true,
            tooltip: {
                title: 'Project',
                content: 'View and manage your project as a file system',
            },
        },
        ...(featureFlags[FEATURE_FLAGS.CUSTOM_PRODUCTS_SIDEBAR] === 'test'
            ? [
                  {
                      identifier: 'Products',
                      label: 'All apps',
                      icon: <IconApps />,
                      onClick: (e?: React.KeyboardEvent) => {
                          if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                              handlePanelTriggerClick('Products')
                          }
                      },
                      showChevron: true,
                      tooltip: {
                          title: 'Apps',
                          content: 'View all apps in your project',
                      },
                  },
              ]
            : []),
    ].filter(Boolean)

    return (
        <Tooltip.Root>
            <div className="flex gap-0 relative">
                <nav
                    className={cn(
                        navBarStyles({
                            isLayoutNavCollapsed,
                            isMobileLayout,
                        })
                    )}
                    ref={containerRef}
                >
                    <div
                        className={cn(
                            'flex justify-between p-1 pl-[5px] items-center',
                            isLayoutNavCollapsed ? 'justify-center' : 'h-[var(--scene-layout-header-height)]'
                        )}
                    >
                        <div
                            className={cn('flex gap-1 rounded-md w-full', {
                                'flex-col items-center pt-px': isLayoutNavCollapsed,
                            })}
                        >
                            <Tooltip.Trigger payload={{ title: 'Switch organization' }} handle={tooltipHandle}>
                                <OrganizationMenu
                                    showName={false}
                                    buttonProps={{
                                        variant: 'panel',
                                        className: cn('px-px', {
                                            hidden: isLayoutNavCollapsed,
                                        }),
                                        iconOnly: isLayoutNavCollapsed,
                                    }}
                                    iconOnly={isLayoutNavCollapsed}
                                />
                            </Tooltip.Trigger>
                            <Tooltip.Trigger
                                payload={{ title: 'Switch project', side: isLayoutNavCollapsed ? 'right' : 'bottom' }}
                                handle={tooltipHandle}
                            >
                                <ProjectMenu
                                    buttonProps={{
                                        className: 'max-w-[175px]',
                                        variant: 'panel',
                                        iconOnly: isLayoutNavCollapsed,
                                    }}
                                    iconOnly={isLayoutNavCollapsed}
                                />
                            </Tooltip.Trigger>
                            <RecentItemsMenu />
                        </div>
                    </div>

                    <div className="z-[var(--z-main-nav)] flex flex-col flex-1 overflow-y-auto">
                        <ScrollableShadows
                            className={cn('flex-1', { 'rounded-tr-sm': !isLayoutPanelVisible })}
                            innerClassName="overflow-y-auto"
                            direction="vertical"
                            styledScrollbars
                        >
                            <ListBox className="flex flex-col gap-px">
                                <div
                                    className={cn('px-1 flex flex-col gap-px', {
                                        'items-center': isLayoutNavCollapsed,
                                    })}
                                >
                                    {navItems.map((item) => {
                                        const iconClassName = 'flex text-tertiary group-hover:text-primary'

                                        const listItem = (
                                            <ListBox.Item
                                                key={item.identifier}
                                                asChild
                                                onClick={() => item.onClick?.()}
                                                onKeyDown={(e) => {
                                                    if (e.key === 'Enter') {
                                                        item.onClick?.(e)
                                                    }
                                                }}
                                            >
                                                {item.showChevron ? (
                                                    <Tooltip.Trigger
                                                        payload={{
                                                            title: item.tooltip?.title,
                                                            content: item.tooltip?.content,
                                                            side: 'right',
                                                        }}
                                                        handle={tooltipHandle}
                                                        render={
                                                            <ButtonPrimitive
                                                                active={
                                                                    activePanelIdentifier === item.identifier ||
                                                                    activePanelIdentifierFromUrl === item.identifier
                                                                }
                                                                className="group"
                                                                menuItem={!isLayoutNavCollapsed}
                                                                iconOnly={isLayoutNavCollapsed}
                                                                // tooltip={tooltip}
                                                                // tooltipPlacement="right"
                                                                // tooltipDocLink={item.documentationUrl}
                                                                data-attr={`menu-item-${item.identifier.toString().toLowerCase()}`}
                                                            >
                                                                <span className={iconClassName}>{item.icon}</span>
                                                                {!isLayoutNavCollapsed && (
                                                                    <>
                                                                        <span className="truncate">{item.label}</span>
                                                                        <span className="ml-auto pr-1">
                                                                            <IconChevronRight className="size-3 text-tertiary" />
                                                                        </span>
                                                                    </>
                                                                )}
                                                            </ButtonPrimitive>
                                                        }
                                                    />
                                                ) : (
                                                    <Tooltip.Trigger
                                                        payload={{
                                                            title: item.tooltip?.title,
                                                            content: item.tooltip?.content,
                                                            side: 'right',
                                                        }}
                                                        handle={tooltipHandle}
                                                        render={
                                                            <ButtonGroupPrimitive
                                                                fullWidth
                                                                className="flex justify-center [&>span]:w-full [&>span]:flex [&>span]:justify-center"
                                                            >
                                                                <Link
                                                                    data-attr={`menu-item-${item.identifier
                                                                        .toString()
                                                                        .toLowerCase()}`}
                                                                    buttonProps={{
                                                                        menuItem: !isLayoutNavCollapsed,
                                                                        className: 'group',
                                                                        iconOnly: isLayoutNavCollapsed,
                                                                        active: isStaticNavItemActive(item.identifier),
                                                                    }}
                                                                    to={item.to}
                                                                    // tooltip={tooltip}
                                                                    // tooltipPlacement="right"
                                                                    // tooltipDocLink={item.documentationUrl}
                                                                >
                                                                    <span className={iconClassName}>{item.icon}</span>
                                                                    {!isLayoutNavCollapsed && (
                                                                        <span className="truncate">{item.label}</span>
                                                                    )}
                                                                </Link>
                                                            </ButtonGroupPrimitive>
                                                        }
                                                    />
                                                )}
                                            </ListBox.Item>
                                        )

                                        if (item.identifier === 'ProjectHomepage') {
                                            return (
                                                <ContextMenu key={item.identifier}>
                                                    <ContextMenuTrigger asChild>{listItem}</ContextMenuTrigger>
                                                    <ContextMenuContent className="max-w-[300px]">
                                                        <ContextMenuGroup>
                                                            <ContextMenuItem asChild>
                                                                <ButtonPrimitive
                                                                    menuItem
                                                                    onClick={() => setIsConfigurePinnedTabsOpen(true)}
                                                                >
                                                                    <IconGear /> Configure tabs & home
                                                                </ButtonPrimitive>
                                                            </ContextMenuItem>
                                                        </ContextMenuGroup>
                                                    </ContextMenuContent>
                                                </ContextMenu>
                                            )
                                        } else if (item.identifier === 'Activity' && item.to) {
                                            return (
                                                <ContextMenu key={item.identifier}>
                                                    <ContextMenuTrigger asChild>{listItem}</ContextMenuTrigger>
                                                    <ContextMenuContent className="max-w-[300px]">
                                                        <ContextMenuGroup>
                                                            <BrowserLikeMenuItems
                                                                MenuItem={ContextMenuItem}
                                                                href={item.to}
                                                                resetPanelLayout={resetPanelLayout}
                                                            />
                                                        </ContextMenuGroup>
                                                    </ContextMenuContent>
                                                </ContextMenu>
                                            )
                                        }

                                        return listItem
                                    })}
                                </div>

                                <div className="border-b border-primary h-px my-1" />

                                <div
                                    className={cn(
                                        'relative flex flex-col gap-px h-full',
                                        !isLayoutNavCollapsed ? 'pt-1' : 'items-center'
                                    )}
                                >
                                    <PinnedFolder />
                                </div>
                            </ListBox>
                        </ScrollableShadows>

                        <div className="border-b border-primary h-px " />

                        <div className="p-1 flex flex-col gap-px items-center">
                            <DebugNotice isCollapsed={isLayoutNavCollapsed} />
                            <NavPanelAdvertisement />

                            <Tooltip.Trigger
                                payload={{
                                    title: isLayoutNavCollapsed ? 'Expand nav' : 'Collapse nav',
                                    side: 'right',
                                    content: 'Toggle the width of the navigation bar',
                                }}
                                handle={tooltipHandle}
                                render={
                                    <ButtonPrimitive
                                        iconOnly={isLayoutNavCollapsed}
                                        onClick={() => toggleLayoutNavCollapsed(!isLayoutNavCollapsed)}
                                        menuItem={!isLayoutNavCollapsed}
                                    >
                                        {isLayoutNavCollapsed ? (
                                            <>
                                                <IconSidebarClose className="text-tertiary" />
                                            </>
                                        ) : (
                                            <>
                                                <IconSidebarOpen className="text-tertiary" />
                                                Collapse nav
                                            </>
                                        )}
                                    </ButtonPrimitive>
                                }
                            />

                            {visibleTabs.includes(SidePanelTab.Activation) && (
                                <Tooltip.Trigger
                                    payload={{
                                        title: 'Quick start',
                                        side: 'right',
                                        content:
                                            'Get started with PostHog and learn about everything it can do for you and your product',
                                    }}
                                    handle={tooltipHandle}
                                    render={
                                        <ButtonPrimitive
                                            menuItem={!isLayoutNavCollapsed}
                                            onClick={() =>
                                                sidePanelOpen && selectedTab === SidePanelTab.Activation
                                                    ? closeSidePanel()
                                                    : openSidePanel(SidePanelTab.Activation)
                                            }
                                            data-attr="activation-button"
                                            tooltip={isLayoutNavCollapsed ? 'Quick start' : undefined}
                                            tooltipPlacement="right"
                                            iconOnly={isLayoutNavCollapsed}
                                        >
                                            <span>
                                                <SidePanelActivationIcon size={16} />
                                            </span>
                                            {!isLayoutNavCollapsed && 'Quick start'}
                                        </ButtonPrimitive>
                                    }
                                />
                            )}

                            <Tooltip.Trigger
                                payload={{
                                    title: 'Toolbar',
                                    side: 'right',
                                    content: 'Toolbar launches PostHog right in your app or website',
                                }}
                                handle={tooltipHandle}
                                render={
                                    <Link
                                        buttonProps={{
                                            menuItem: !isLayoutNavCollapsed,
                                            className: 'group',
                                            iconOnly: isLayoutNavCollapsed,
                                            active: isStaticNavItemActive('Toolbar'),
                                        }}
                                        to={urls.toolbarLaunch()}
                                        onClick={() => {
                                            handleStaticNavbarItemClick(urls.toolbarLaunch(), true)
                                        }}
                                        data-attr="menu-item-toolbar"
                                    >
                                        <span className="flex text-tertiary group-hover:text-primary">
                                            <IconToolbar />
                                        </span>
                                        {!isLayoutNavCollapsed && 'Toolbar'}
                                    </Link>
                                }
                            />

                            <AppShortcut
                                name="Settings"
                                keybind={[['command', 'option', 's']]}
                                intent="Open settings"
                                interaction="click"
                            >
                                <Tooltip.Trigger
                                    payload={{
                                        title: 'Settings',
                                        side: 'right',
                                        content: 'Manage your project settings and preferences',
                                        keyboardShortcut: [['command', 'option', 's']],
                                    }}
                                    handle={tooltipHandle}
                                    render={
                                        <Link
                                            buttonProps={{
                                                menuItem: !isLayoutNavCollapsed,
                                                className: 'group',
                                                iconOnly: isLayoutNavCollapsed,
                                                active: isStaticNavItemActive('Settings'),
                                            }}
                                            to={urls.settings('project')}
                                            onClick={() => {
                                                handleStaticNavbarItemClick(urls.settings('project'), true)
                                            }}
                                            data-attr="menu-item-settings"
                                        >
                                            <span className="flex text-tertiary group-hover:text-primary">
                                                <IconGear />
                                            </span>
                                            {!isLayoutNavCollapsed && 'Settings'}
                                        </Link>
                                    }
                                />
                            </AppShortcut>

                            <AccountMenu
                                align="end"
                                side="right"
                                alignOffset={10}
                                trigger={
                                    <ButtonPrimitive
                                        menuItem={!isLayoutNavCollapsed}
                                        tooltip={isLayoutNavCollapsed ? 'Account' : undefined}
                                        tooltipPlacement="right"
                                        iconOnly={isLayoutNavCollapsed}
                                        data-attr="menu-item-me"
                                    >
                                        <ProfilePicture user={user} size="xs" />
                                        {!isLayoutNavCollapsed && (
                                            <>
                                                {user?.first_name ? (
                                                    <span>{user?.first_name}</span>
                                                ) : (
                                                    <span>{user?.email}</span>
                                                )}
                                                <IconChevronRight className="size-3 text-secondary ml-auto" />
                                            </>
                                        )}
                                    </ButtonPrimitive>
                                }
                            />
                        </div>
                    </div>
                    {!isMobileLayout && (
                        <Resizer
                            logicKey="panel-layout-navbar"
                            placement="right"
                            containerRef={containerRef}
                            closeThreshold={100}
                            onToggleClosed={(shouldBeClosed) => toggleLayoutNavCollapsed(shouldBeClosed)}
                            onDoubleClick={() => toggleLayoutNavCollapsed()}
                            data-attr="tree-navbar-resizer"
                            className={cn('top-[var(--scene-layout-header-height)] right-[-1px]', {
                                // If first tab is not active, we move the line down to match up with the curve (only present if not first tab is active)
                                'top-[calc(var(--scene-layout-header-height)+10px)]': !firstTabIsActive,
                                'top-0': isLayoutPanelVisible,
                            })}
                            offset={0}
                        />
                    )}
                </nav>

                {children}

                {isMobileLayout && isLayoutNavbarVisible && !isLayoutPanelVisible && (
                    <div
                        onClick={() => {
                            showLayoutNavBar(false)
                            clearActivePanelIdentifier()
                        }}
                        className="z-[var(--z-layout-navbar-under)] fixed inset-0 w-screen h-screen bg-fill-highlight-200 lg:bg-transparent"
                    />
                )}

                {isMobileLayout && isLayoutNavbarVisible && isLayoutPanelVisible && (
                    <div
                        onClick={() => {
                            showLayoutPanel(false)
                            clearActivePanelIdentifier()
                        }}
                        className="z-[var(--z-layout-navbar-over)] fixed inset-0 w-screen h-screen bg-fill-highlight-200 lg:bg-transparent"
                    />
                )}
            </div>
            <ConfigurePinnedTabsModal
                isOpen={isConfigurePinnedTabsOpen}
                onClose={() => setIsConfigurePinnedTabsOpen(false)}
            />
        </Tooltip.Root>
    )
}
