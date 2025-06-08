import {
    IconCdCase,
    IconChevronRight,
    IconClock,
    IconDatabase,
    IconFolderOpen,
    IconGear,
    IconHome,
    IconPeople,
    IconSearch,
    IconShortcut,
    IconToolbar,
} from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { Popover } from 'lib/lemon-ui/Popover'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ListBox } from 'lib/ui/ListBox/ListBox'
import { cn } from 'lib/utils/css-classes'
import { memo, useRef } from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'
import { panelLayoutLogic, PanelLayoutNavIdentifier } from '~/layout/panel-layout/panelLayoutLogic'
import { PinnedFolder } from '~/layout/panel-layout/PinnedFolder/PinnedFolder'
import { SidePanelTab } from '~/types'

import { navigationLogic } from '../navigation/navigationLogic'
import { AccountPopoverOverlay } from '../navigation/TopBar/AccountPopover'
import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { SidePanelActivationIcon } from '../navigation-3000/sidepanel/panels/activation/SidePanelActivation'
import { sidePanelLogic } from '../navigation-3000/sidepanel/sidePanelLogic'
import { sidePanelStateLogic } from '../navigation-3000/sidepanel/sidePanelStateLogic'
import { OrganizationDropdownMenu } from './OrganizationDropdownMenu'
import { UniversalKeyboardShortcut } from '~/layout/UniversalKeyboardShortcuts/UniversalKeyboardShortcut'
import { universalKeyboardShortcutsLogic } from '../UniversalKeyboardShortcuts/universalKeyboardShortcutsLogic'
import { KeyboardShortcut } from '../navigation-3000/components/KeyboardShortcut'

const navBarStyles = cva({
    base: 'flex flex-col max-h-screen relative min-h-screen bg-surface-tertiary z-[var(--z-layout-navbar)] border-r border-primary relative',
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

type PanelLayoutNavBarItem = {
    identifier: string
    id: React.ReactNode
    icon: React.ReactNode
    onClick: (e?: React.KeyboardEvent) => void
    tooltip?: string | React.ReactNode
    tooltipDocLink?: string
    keyboardShortcut: string
    showChevron?: boolean
    to?: string
    // itemSideAction?: (item: PanelLayoutNavIdentifier) => React.ReactNode
    ref?: React.RefObject<HTMLButtonElement>
}


export function PanelLayoutNavBar({ children }: { children: React.ReactNode }): JSX.Element {
    const { toggleSearchBar } = useActions(commandBarLogic)
    const containerRef = useRef<HTMLDivElement | null>(null)

    // Create refs for nav items that need them
    const productsRef = useRef<HTMLButtonElement>(null)
    const projectRef = useRef<HTMLButtonElement>(null)
    const dataRef = useRef<HTMLButtonElement>(null)
    const peopleRef = useRef<HTMLButtonElement>(null)
    const shortcutsRef = useRef<HTMLButtonElement>(null)

    const {
        showLayoutPanel,
        setActivePanelIdentifier,
        clearActivePanelIdentifier,
        toggleLayoutNavCollapsed,
        showLayoutNavBar,
    } = useActions(panelLayoutLogic)
    const {
        isLayoutPanelVisible,
        activePanelIdentifier,
        mainContentRef,
        isLayoutPanelPinned,
        isLayoutNavCollapsed,
        isLayoutNavbarVisible,
    } = useValues(panelLayoutLogic)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { closeAccountPopover, toggleAccountPopover } = useActions(navigationLogic)
    const { user } = useValues(userLogic)
    const { isAccountPopoverOpen } = useValues(navigationLogic)
    const { visibleTabs, sidePanelOpen, selectedTab } = useValues(sidePanelLogic)
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)
    const { isDev } = useValues(preflightLogic)
    const { isKeyboardShortcutsVisible } = useValues(universalKeyboardShortcutsLogic)

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


    const NavBarItem = memo(({ item }: { item: PanelLayoutNavBarItem }): JSX.Element => {
        return <>
            {item.showChevron ? (
                <UniversalKeyboardShortcut name={item.identifier} category={'nav'} keybind={item.keyboardShortcut} ref={item.ref} asChild>
                    <ButtonPrimitive
                        active={activePanelIdentifier === item.identifier}
                        className="group"
                        menuItem={!isLayoutNavCollapsed}
                        iconOnly={isLayoutNavCollapsed}
                        tooltip={item.tooltip}
                        tooltipPlacement="right"
                        tooltipDocLink={item.tooltipDocLink}
                        onClick={() => {
                            handlePanelTriggerClick(item.identifier as PanelLayoutNavIdentifier)
                        }}
                        data-attr={`menu-item-${item.identifier.toString().toLowerCase()}`}
                        ref={item.ref}
                    >
                        <span
                            className={`flex text-tertiary group-hover:text-primary ${isLayoutNavCollapsed ? '[&_svg]:size-5' : ''
                                }`}
                        >
                            {item.icon}
                        </span>

                        {!isLayoutNavCollapsed && (
                            <>
                                <span className="truncate">{item.id}</span>
                                <span className="ml-auto pr-1">
                                    <IconChevronRight className="size-3 text-tertiary" />
                                </span>
                            </>
                        )}
                    </ButtonPrimitive>
                </UniversalKeyboardShortcut>

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
                        }}
                        to={item.to}
                        tooltip={item.tooltip}
                        tooltipPlacement="right"
                        tooltipDocLink={item.tooltipDocLink}
                        onClick={() => handleStaticNavbarItemClick(item.to, true)}
                    >
                        <span
                            className={`flex text-tertiary group-hover:text-primary ${isLayoutNavCollapsed ? '[&_svg]:size-5' : ''
                                }`}
                        >
                            {item.icon}
                        </span>

                        {!isLayoutNavCollapsed && (
                            <span className="truncate">{item.id}</span>
                        )}
                    </Link>
                </ButtonGroupPrimitive>
            )}
        </>
    })


    const navItems: PanelLayoutNavBarItem[] = [
        ...(isLayoutNavCollapsed
            ? [
                {
                    identifier: 'Search',
                    id: 'Search',
                    icon: <IconSearch />,
                    onClick: () => {
                        toggleSearchBar()
                    },
                    keyboardShortcut: 'cmd k',
                    tooltip: (
                        <div className="flex flex-col gap-0.5">
                            <span>
                                For search, press <KeyboardShortcut command k />
                            </span>
                            <span>
                                For commands, press <KeyboardShortcut command shift k />
                            </span>
                        </div>
                    ),
                },
            ]
            : []),
        {
            identifier: 'ProjectHomepage',
            id: 'Home',
            icon: <IconHome />,
            to: urls.projectHomepage(),
            onClick: () => {
                handleStaticNavbarItemClick(urls.projectHomepage(), true)
            },
            tooltip: isLayoutNavCollapsed ? 'Home' : null,
            keyboardShortcut: 'command shift h',
        },
        {
            identifier: 'PanelProducts',
            id: <>Products {isKeyboardShortcutsVisible ? <KeyboardShortcut command shift o /> : null}</>,
            icon: <IconCdCase />,
            onClick: (e?: React.KeyboardEvent) => {
                if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                    handlePanelTriggerClick('PanelProducts')
                }
            },
            showChevron: true,
            ref: productsRef,
            keyboardShortcut: 'command shift o',
        },
        {
            identifier: 'PanelProject',
            id: <>Project {isKeyboardShortcutsVisible ? <KeyboardShortcut command shift p /> : null}</>,
            icon: <IconFolderOpen className="stroke-[1.2]" />,
            onClick: (e?: React.KeyboardEvent) => {
                if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                    handlePanelTriggerClick('PanelProject')
                }
            },
            showChevron: true,
            tooltip: isLayoutNavCollapsed
                ? isLayoutPanelVisible && activePanelIdentifier === 'Project'
                    ? 'Close project tree'
                    : 'Open project tree'
                : null,
            ref: projectRef,
            keyboardShortcut: 'command shift p',
        },
        {
            identifier: 'PanelData',
            id: <>Data {isKeyboardShortcutsVisible ? <KeyboardShortcut command shift d /> : null}</>,
            icon: <IconDatabase />,
            onClick: (e?: React.KeyboardEvent) => {
                if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                    handlePanelTriggerClick('PanelData')
                }
            },
            showChevron: true,
            ref: dataRef,
            keyboardShortcut: 'command shift d',
        },
        {
            identifier: 'PanelPeople',
            id: <>People {isKeyboardShortcutsVisible ? <KeyboardShortcut command shift u /> : null}</>,
            icon: <IconPeople />,
            onClick: (e?: React.KeyboardEvent) => {
                if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                    handlePanelTriggerClick('PanelPeople')
                }
            },
            showChevron: true,
            tooltipDocLink: 'https://posthog.com/docs/data/persons',
            ref: peopleRef,
            keyboardShortcut: 'command shift u',
        },
        {
            identifier: 'PanelShortcuts',
            id: <>Shortcuts {isKeyboardShortcutsVisible ? <KeyboardShortcut command shift s /> : null}</>,
            icon: <IconShortcut />,
            onClick: (e?: React.KeyboardEvent) => {
                if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                    handlePanelTriggerClick('PanelShortcuts')
                }
            },
            showChevron: true,
            ref: shortcutsRef,
            keyboardShortcut: 'command shift s',
        },
        {
            identifier: 'Activity',
            id: <>Activity</>,
            icon: <IconClock />,
            to: urls.activity(),
            onClick: () => {
                handleStaticNavbarItemClick(urls.activity(), true)
            },
            tooltip: 'Activity',
            tooltipDocLink: 'https://posthog.com/docs/data/events',
            keyboardShortcut: 'shift a',
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
                    <div className={`flex justify-between p-1 ${isLayoutNavCollapsed ? 'justify-center' : ''}`}>
                        <OrganizationDropdownMenu />

                        {!isLayoutNavCollapsed && (
                            <div
                                className={`flex gap-px ${isLayoutNavCollapsed ? 'justify-center' : ''}`}
                                aria-label="Add a new item menu actions"
                            >
                                <ButtonPrimitive
                                    size="base"
                                    iconOnly
                                    onClick={toggleSearchBar}
                                    data-attr="tree-navbar-search-button"
                                    tooltip={
                                        <div className="flex flex-col gap-0.5">
                                            <span>
                                                For search, press <KeyboardShortcut command k />
                                            </span>
                                            <span>
                                                For commands, press <KeyboardShortcut command shift k />
                                            </span>
                                        </div>
                                    }
                                >
                                    <IconSearch className="text-secondary" />
                                </ButtonPrimitive>
                            </div>
                        )}
                    </div>

                    <div className="z-[var(--z-main-nav)] flex flex-col flex-1 overflow-y-auto">
                        <ScrollableShadows
                            className="flex-1"
                            innerClassName="overflow-y-auto"
                            direction="vertical"
                            styledScrollbars
                        >
                            <ListBox className="flex flex-col gap-px">
                                <div
                                    className={`px-1 flex flex-col gap-px ${isLayoutNavCollapsed ? 'items-center' : ''
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
                                            <NavBarItem item={item} />
                                        </ListBox.Item>
                                    ))}
                                </div>

                                <div className="border-b border-primary h-px my-1" />

                                <div
                                    className={cn(
                                        'flex flex-col gap-px h-full',
                                        !isLayoutNavCollapsed ? 'pt-1' : 'items-center'
                                    )}
                                >
                                    <PinnedFolder />
                                </div>
                            </ListBox>
                        </ScrollableShadows>

                        <div className="border-b border-primary h-px " />

                        {/* 
                            Extra padding to compensate for dev mode debug notice... 
                            not sure how better to do this other than lower the notices z-index.. 
                        */}
                        <div
                            className={`pt-1 px-1 flex flex-col gap-px ${isLayoutNavCollapsed ? 'items-center' : ''} ${isDev ? 'pb-10' : 'pb-2'
                                }`}
                        >
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
                                }}
                                to={urls.toolbarLaunch()}
                                onClick={() => {
                                    handleStaticNavbarItemClick(urls.toolbarLaunch(), true)
                                }}
                                tooltip={isLayoutNavCollapsed ? 'Toolbar' : undefined}
                                tooltipDocLink="https://posthog.com/docs/toolbar"
                                tooltipPlacement="right"
                            >
                                <span
                                    className={`flex text-tertiary group-hover:text-primary ${isLayoutNavCollapsed ? '[&_svg]:size-5' : ''
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
                                }}
                                to={urls.settings('project')}
                                data-attr={Scene.Settings}
                                onClick={() => {
                                    handleStaticNavbarItemClick(urls.settings('project'), true)
                                }}
                                tooltip={isLayoutNavCollapsed ? 'Settings' : undefined}
                                tooltipPlacement="right"
                            >
                                <span
                                    className={`flex text-tertiary group-hover:text-primary ${isLayoutNavCollapsed ? '[&_svg]:size-5' : ''
                                        }`}
                                >
                                    <IconGear />
                                </span>
                                {!isLayoutNavCollapsed && 'Settings'}
                            </Link>

                            <Popover
                                overlay={<AccountPopoverOverlay />}
                                visible={isAccountPopoverOpen}
                                onClickOutside={closeAccountPopover}
                                placement="right-end"
                                className="min-w-70"
                            >
                                <ButtonPrimitive
                                    menuItem={!isLayoutNavCollapsed}
                                    active={isAccountPopoverOpen}
                                    onClick={toggleAccountPopover}
                                    tooltip={isLayoutNavCollapsed ? 'Account' : undefined}
                                    tooltipPlacement="right"
                                    iconOnly={isLayoutNavCollapsed}
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
                            </Popover>
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
