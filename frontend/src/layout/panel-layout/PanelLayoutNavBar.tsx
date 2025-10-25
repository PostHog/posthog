import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useRef } from 'react'

import {
    IconApps,
    IconChevronRight,
    IconClock,
    IconDatabase,
    IconDatabaseBolt,
    IconFolderOpen,
    IconGear,
    IconHome,
    IconPeople,
    IconShortcut,
    IconToolbar,
} from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { AccountMenu } from 'lib/components/Account/AccountMenu'
import { DebugNotice } from 'lib/components/DebugNotice'
import { NavPanelAdvertisement } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisement'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ListBox } from 'lib/ui/ListBox/ListBox'
import { cn } from 'lib/utils/css-classes'
import { removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { PinnedFolder } from '~/layout/panel-layout/PinnedFolder/PinnedFolder'
import { PanelLayoutNavIdentifier, panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { SidePanelTab } from '~/types'

import { OrganizationMenu } from '../../lib/components/Account/OrganizationMenu'
import { ProjectMenu } from '../../lib/components/Account/ProjectMenu'
import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { SidePanelActivationIcon } from '../navigation-3000/sidepanel/panels/activation/SidePanelActivation'
import { sidePanelLogic } from '../navigation-3000/sidepanel/sidePanelLogic'
import { sidePanelStateLogic } from '../navigation-3000/sidepanel/sidePanelStateLogic'
import { sceneLayoutLogic } from '../scenes/sceneLayoutLogic'

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
    const {
        showLayoutPanel,
        setActivePanelIdentifier,
        clearActivePanelIdentifier,
        toggleLayoutNavCollapsed,
        showLayoutNavBar,
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
    const { sceneLayoutConfig } = useValues(sceneLayoutLogic)

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

    const navItems: {
        identifier: string
        label: string
        icon: React.ReactNode
        showChevron?: boolean
        to?: string
        onClick?: (e?: React.KeyboardEvent) => void
        tooltip?: React.ReactNode
        tooltipDocLink?: string
    }[] = [
        {
            identifier: 'ProjectHomepage',
            label: 'Home',
            icon: <IconHome />,
            to: urls.projectHomepage(),
            onClick: () => {
                handleStaticNavbarItemClick(urls.projectHomepage(), true)
            },
            tooltip: 'Home',
        },
        {
            identifier: 'Products',
            label: 'Apps',
            icon: <IconApps />,
            onClick: (e) => {
                if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                    handlePanelTriggerClick('Products')
                }
            },
            showChevron: true,
            tooltip: isLayoutPanelVisible && activePanelIdentifier === 'Products' ? 'Close products' : 'Open products',
            tooltipDocLink: 'https://posthog.com/blog/redesigned-nav-menu',
        },
        {
            identifier: 'Project',
            label: 'Project',
            icon: <IconFolderOpen className="stroke-[1.2]" />,
            onClick: (e) => {
                if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                    handlePanelTriggerClick('Project')
                }
            },
            showChevron: true,
            tooltip:
                isLayoutPanelVisible && activePanelIdentifier === 'Project'
                    ? 'Close project tree'
                    : 'Open project tree',
            tooltipDocLink: 'https://posthog.com/blog/redesigned-nav-menu',
        },
        {
            identifier: 'Database',
            label: 'Data warehouse',
            icon: <IconDatabaseBolt />,
            onClick: (e) => {
                if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                    handlePanelTriggerClick('Database')
                }
            },
            showChevron: true,
            tooltip:
                isLayoutPanelVisible && activePanelIdentifier === 'Database'
                    ? 'Close data warehouse'
                    : 'Open data warehouse',
            tooltipDocLink: 'https://posthog.com/docs/data-warehouse/sql',
        },
        {
            identifier: 'DataManagement',
            label: 'Data management',
            icon: <IconDatabase />,
            onClick: (e) => {
                if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                    handlePanelTriggerClick('DataManagement')
                }
            },
            showChevron: true,
            tooltip:
                isLayoutPanelVisible && activePanelIdentifier === 'DataManagement'
                    ? 'Close data management'
                    : 'Open data management',
            tooltipDocLink: 'https://posthog.com/docs/data',
        },
        {
            identifier: 'People',
            label: 'People',
            icon: <IconPeople />,
            onClick: (e) => {
                if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                    handlePanelTriggerClick('People')
                }
            },
            showChevron: true,
            tooltip: isLayoutPanelVisible && activePanelIdentifier === 'People' ? 'Close people' : 'Open people',
            tooltipDocLink: 'https://posthog.com/docs/data/persons',
        },
        {
            identifier: 'Shortcuts',
            label: 'Shortcuts',
            icon: <IconShortcut />,
            onClick: (e) => {
                if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                    handlePanelTriggerClick('Shortcuts')
                }
            },
            showChevron: true,
            tooltip:
                isLayoutPanelVisible && activePanelIdentifier === 'Shortcuts' ? 'Close shortcuts' : 'Open shortcuts',
            tooltipDocLink: 'https://posthog.com/blog/redesigned-nav-menu',
        },
        {
            identifier: 'Activity',
            label: 'Activity',
            icon: <IconClock />,
            to: urls.activity(),
            onClick: () => {
                handleStaticNavbarItemClick(urls.activity(), true)
            },
            tooltip: 'Activity',
            tooltipDocLink: 'https://posthog.com/docs/data/events',
        },
    ]

    return (
        <>
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
                        className={`flex justify-between p-1 pl-[5px] items-center ${isLayoutNavCollapsed ? 'justify-center' : 'h-[var(--scene-layout-header-height)]'}`}
                    >
                        <div
                            className={cn(
                                'flex gap-1 rounded-md w-full',
                                isLayoutNavCollapsed && 'flex-col items-center pt-px'
                            )}
                        >
                            <OrganizationMenu
                                showName={false}
                                buttonProps={{
                                    variant: 'panel',
                                    className: 'px-px',
                                    iconOnly: isLayoutNavCollapsed,
                                    tooltipCloseDelayMs: 0,
                                    tooltipPlacement: 'bottom',
                                    tooltip: 'Switch organization',
                                }}
                                iconOnly={isLayoutNavCollapsed}
                            />
                            <ProjectMenu
                                buttonProps={{
                                    className: 'max-w-[175px]',
                                    variant: 'panel',
                                    tooltipCloseDelayMs: 0,
                                    iconOnly: isLayoutNavCollapsed,
                                    tooltipPlacement: 'bottom',
                                    tooltip: 'Switch project',
                                }}
                                iconOnly={isLayoutNavCollapsed}
                            />
                        </div>
                    </div>

                    <div className="z-[var(--z-main-nav)] flex flex-col flex-1 overflow-y-auto">
                        <ScrollableShadows
                            className={cn('flex-1', !isLayoutPanelVisible && 'rounded-tr-sm')}
                            innerClassName="overflow-y-auto"
                            direction="vertical"
                            styledScrollbars
                        >
                            <ListBox className="flex flex-col gap-px">
                                <div
                                    className={`px-1 flex flex-col gap-px ${
                                        isLayoutNavCollapsed ? 'items-center' : ''
                                    }`}
                                >
                                    {navItems.map((item) => (
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
                                                <ButtonPrimitive
                                                    active={
                                                        activePanelIdentifier === item.identifier ||
                                                        activePanelIdentifierFromUrl === item.identifier
                                                    }
                                                    className="group"
                                                    menuItem={!isLayoutNavCollapsed}
                                                    iconOnly={isLayoutNavCollapsed}
                                                    tooltip={isLayoutNavCollapsed ? item.tooltip : undefined}
                                                    tooltipPlacement="right"
                                                    tooltipDocLink={item.tooltipDocLink}
                                                    data-attr={`menu-item-${item.identifier.toString().toLowerCase()}`}
                                                >
                                                    <span
                                                        className={`flex text-tertiary group-hover:text-primary ${
                                                            isLayoutNavCollapsed ? '[&_svg]:size-5' : ''
                                                        }`}
                                                    >
                                                        {item.icon}
                                                    </span>

                                                    {!isLayoutNavCollapsed && (
                                                        <>
                                                            <span className="truncate">{item.label}</span>
                                                            <span className="ml-auto pr-1">
                                                                <IconChevronRight className="size-3 text-tertiary" />
                                                            </span>
                                                        </>
                                                    )}
                                                </ButtonPrimitive>
                                            ) : (
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
                                                        tooltip={isLayoutNavCollapsed ? item.tooltip : undefined}
                                                        tooltipPlacement="right"
                                                        tooltipDocLink={item.tooltipDocLink}
                                                    >
                                                        <span
                                                            className={`flex text-tertiary group-hover:text-primary ${
                                                                isLayoutNavCollapsed ? '[&_svg]:size-5' : ''
                                                            }`}
                                                        >
                                                            {item.icon}
                                                        </span>

                                                        {!isLayoutNavCollapsed && (
                                                            <span className="truncate">{item.label}</span>
                                                        )}
                                                    </Link>
                                                </ButtonGroupPrimitive>
                                            )}
                                        </ListBox.Item>
                                    ))}
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
                            {visibleTabs.includes(SidePanelTab.Activation) && (
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
                                    <span className={`${isLayoutNavCollapsed ? 'size-5' : ''}`}>
                                        <SidePanelActivationIcon size={16} />
                                    </span>
                                    {!isLayoutNavCollapsed && 'Quick start'}
                                </ButtonPrimitive>
                            )}
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
                                tooltip={isLayoutNavCollapsed ? 'Toolbar' : undefined}
                                tooltipDocLink="https://posthog.com/docs/toolbar"
                                tooltipPlacement="right"
                                data-attr="menu-item-toolbar"
                            >
                                <span
                                    className={`flex text-tertiary group-hover:text-primary ${
                                        isLayoutNavCollapsed ? '[&_svg]:size-5' : ''
                                    }`}
                                >
                                    <IconToolbar />
                                </span>
                                {!isLayoutNavCollapsed && 'Toolbar'}
                            </Link>

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
                                tooltip={isLayoutNavCollapsed ? 'Settings' : undefined}
                                tooltipPlacement="right"
                                data-attr="menu-item-settings"
                            >
                                <span
                                    className={`flex text-tertiary group-hover:text-primary ${
                                        isLayoutNavCollapsed ? '[&_svg]:size-5' : ''
                                    }`}
                                >
                                    <IconGear />
                                </span>
                                {!isLayoutNavCollapsed && 'Settings'}
                            </Link>

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
                                        <ProfilePicture user={user} size={isLayoutNavCollapsed ? 'md' : 'xs'} />
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
                            className={cn({
                                'top-[calc(var(--scene-layout-header-height)+4px)]': true,
                                'top-0': isLayoutPanelVisible || sceneLayoutConfig?.layout === 'app-raw-no-header',
                            })}
                            offset={-1}
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
        </>
    )
}
