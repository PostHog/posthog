import {
    IconChevronRight,
    IconClock,
    IconDashboard,
    IconDatabase,
    IconFolderOpen,
    IconGear,
    IconHome,
    IconNotebook,
    IconPeople,
    IconSearch,
    IconToolbar,
} from '@posthog/icons'
import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Popover } from 'lib/lemon-ui/Popover'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Button } from 'lib/ui/Button/Button'
import { ListBox } from 'lib/ui/ListBox/ListBox'
import { cn } from 'lib/utils/css-classes'
import { useRef } from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { panelLayoutLogic, PanelLayoutNavIdentifier } from '~/layout/panel-layout/panelLayoutLogic'
import { SidePanelTab } from '~/types'

import { navigationLogic } from '../navigation/navigationLogic'
import { AccountPopoverOverlay } from '../navigation/TopBar/AccountPopover'
import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { SidePanelActivationIcon } from '../navigation-3000/sidepanel/panels/activation/SidePanelActivation'
import { sidePanelLogic } from '../navigation-3000/sidepanel/sidePanelLogic'
import { sidePanelStateLogic } from '../navigation-3000/sidepanel/sidePanelStateLogic'
import { OrganizationDropdownMenu } from './OrganizationDropdownMenu'

const panelStyles = cva({
    base: 'z-[var(--z-project-panel-layout)] h-screen left-0',
    variants: {
        isLayoutPanelVisible: {
            true: 'block',
            false: 'hidden',
        },
    },
    defaultVariants: {
        isLayoutPanelVisible: false,
    },
})

export function PanelLayoutNavBar({ children }: { children: React.ReactNode }): JSX.Element {
    const { toggleSearchBar } = useActions(commandBarLogic)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { showLayoutPanel, setActivePanelIdentifier, clearActivePanelIdentifier, toggleLayoutNavCollapsed } =
        useActions(panelLayoutLogic)
    const { isLayoutPanelVisible, activePanelIdentifier, mainContentRef, isLayoutPanelPinned, isLayoutNavCollapsed } =
        useValues(panelLayoutLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { mobileLayout: isMobileLayout, navbarItems } = useValues(navigation3000Logic)
    const { closeAccountPopover, toggleAccountPopover } = useActions(navigationLogic)
    const { user } = useValues(userLogic)
    const { isAccountPopoverOpen } = useValues(navigationLogic)
    const { visibleTabs, sidePanelOpen, selectedTab } = useValues(sidePanelLogic)
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)
    const { isDev } = useValues(preflightLogic)

    function handlePanelTriggerClick(item: PanelLayoutNavIdentifier): void {
        if (!isLayoutPanelVisible) {
            showLayoutPanel(true)
        } else {
            showLayoutPanel(false)
            clearActivePanelIdentifier()
        }

        if (activePanelIdentifier !== item) {
            setActivePanelIdentifier(item)
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
        if (to) {
            router.actions.push(to)
        }
    }

    const filteredNavItemsIdentifiers = [
        'ProjectHomepage',
        'Max',
        'Activity',
        'Dashboards',
        'Notebooks',
        'DataManagement',
        'PersonsManagement',
    ]
    const navItems = [
        ...(isLayoutNavCollapsed
            ? [
                  {
                      identifier: 'Search',
                      id: 'Search',
                      icon: <IconSearch />,
                      onClick: () => {
                          toggleSearchBar()
                      },
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
        },
        {
            identifier: 'Project',
            id: 'Project',
            icon: <IconFolderOpen className="stroke-[1.2]" />,
            onClick: (e?: React.KeyboardEvent) => {
                if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                    handlePanelTriggerClick('Project')
                }
            },
            showChevron: true,
        },
        {
            identifier: 'Dashboards',
            id: 'Dashboards',
            icon: <IconDashboard />,
            to: urls.dashboards(),
            onClick: () => {
                handleStaticNavbarItemClick(urls.dashboards(), true)
            },
        },
        {
            identifier: 'Notebooks',
            id: 'Notebooks',
            icon: <IconNotebook />,
            to: urls.notebooks(),
            onClick: () => {
                handleStaticNavbarItemClick(urls.notebooks(), true)
            },
        },
        {
            identifier: 'DataManagement',
            id: 'Data management',
            icon: <IconDatabase />,
            to: urls.eventDefinitions(),
            onClick: () => {
                handleStaticNavbarItemClick(urls.eventDefinitions(), true)
            },
        },
        {
            identifier: 'PersonsManagement',
            id: 'Persons and groups',
            icon: <IconPeople />,
            to: urls.persons(),
            onClick: () => {
                handleStaticNavbarItemClick(urls.persons(), true)
            },
        },
        {
            identifier: 'Activity',
            id: 'Activity',
            icon: <IconClock />,
            to: urls.activity(),
            onClick: () => {
                handleStaticNavbarItemClick(urls.activity(), true)
            },
        },
    ]

    return (
        <>
            <div className="flex gap-0 relative">
                <nav
                    className={cn(
                        'relative flex flex-col max-h-screen min-h-screen bg-surface-tertiary z-[var(--z-project-panel-layout)] border-r border-primary',
                        {
                            'w-[var(--project-navbar-width-collapsed)]': isLayoutNavCollapsed,
                            'w-[var(--project-navbar-width)]': !isLayoutNavCollapsed,
                        }
                    )}
                    ref={containerRef}
                >
                    <div className="flex justify-between p-1">
                        <OrganizationDropdownMenu />

                        {!isLayoutNavCollapsed && (
                            <Button.Root size="base" onClick={() => toggleSearchBar()} data-attr="search-button">
                                <Button.Icon>
                                    <IconSearch className="text-secondary" />
                                </Button.Icon>
                            </Button.Root>
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
                                <div className="px-1 flex flex-col gap-px">
                                    {navItems.map((item) => (
                                        <ListBox.Item
                                            key={item.id}
                                            asChild
                                            onClick={() => item.onClick?.()}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter') {
                                                    item.onClick?.(e)
                                                }
                                            }}
                                        >
                                            <Button.Root
                                                menuItem
                                                active={item.id === 'Project' && isLayoutPanelVisible}
                                                data-attr={`menu-item-${item.identifier.toString().toLowerCase()}`}
                                                className="group"
                                            >
                                                <Button.Icon
                                                    className="text-tertiary group-hover:text-primary"
                                                    size={isLayoutNavCollapsed ? 'lg' : 'base'}
                                                >
                                                    {item.icon}
                                                </Button.Icon>
                                                {!isLayoutNavCollapsed && (
                                                    <>
                                                        <Button.Label menuItem>{item.id}</Button.Label>
                                                        {item.id === 'Project' && (
                                                            <span className="flex items-center gap-px">
                                                                <Button.Icon customIconSize>
                                                                    <IconChevronRight className="size-3 text-secondary" />
                                                                </Button.Icon>
                                                            </span>
                                                        )}
                                                    </>
                                                )}
                                            </Button.Root>
                                        </ListBox.Item>
                                    ))}
                                </div>

                                <div className="border-b border-primary h-px my-1" />

                                <div className="pt-1 px-1">
                                    {!isLayoutNavCollapsed && (
                                        <div className="flex justify-between items-center pl-2 pr-0 pb-2">
                                            <span className="text-xs font-semibold text-quaternary">Products</span>
                                        </div>
                                    )}
                                    <div className="flex flex-col gap-px">
                                        {navbarItems.map((section, index) => (
                                            <ul key={index} className="flex flex-col gap-px ">
                                                {section.map((item) => {
                                                    if (filteredNavItemsIdentifiers.includes(item.identifier)) {
                                                        return null
                                                    }

                                                    const notEnabled =
                                                        item.featureFlag && !featureFlags[item.featureFlag]

                                                    return notEnabled ? null : (
                                                        <ListBox.Item
                                                            asChild
                                                            key={item.identifier}
                                                            onClick={() => {
                                                                handleStaticNavbarItemClick(
                                                                    'to' in item ? item.to : undefined,
                                                                    false
                                                                )
                                                            }}
                                                            onKeyDown={(e) => {
                                                                if (e.key === 'Enter') {
                                                                    handleStaticNavbarItemClick(
                                                                        'to' in item ? item.to : undefined,
                                                                        true
                                                                    )
                                                                }
                                                            }}
                                                        >
                                                            <Button.Root
                                                                menuItem
                                                                to={'to' in item ? item.to : undefined}
                                                                className="group"
                                                                data-attr={`menu-item-${item.identifier
                                                                    .toString()
                                                                    .toLowerCase()}`}
                                                            >
                                                                <Button.Icon
                                                                    className="text-tertiary group-hover:text-primary"
                                                                    size={isLayoutNavCollapsed ? 'lg' : 'base'}
                                                                >
                                                                    {item.icon}
                                                                </Button.Icon>
                                                                {!isLayoutNavCollapsed && (
                                                                    <>
                                                                        <Button.Label menuItem>
                                                                            {item.label}
                                                                        </Button.Label>
                                                                        {item.tag && (
                                                                            <LemonTag
                                                                                type={
                                                                                    item.tag === 'alpha'
                                                                                        ? 'completion'
                                                                                        : item.tag === 'beta'
                                                                                        ? 'warning'
                                                                                        : 'success'
                                                                                }
                                                                                size="small"
                                                                                className="ml-auto"
                                                                            >
                                                                                {item.tag.toUpperCase()}
                                                                            </LemonTag>
                                                                        )}

                                                                        {item.sideAction &&
                                                                            item.identifier === 'SavedInsights' && (
                                                                                <Button.Icon
                                                                                    isTriggerRight
                                                                                    isTrigger
                                                                                    onClick={(e) => {
                                                                                        e.preventDefault()
                                                                                        e.stopPropagation()
                                                                                        e.nativeEvent.stopImmediatePropagation()
                                                                                        router.actions.push(
                                                                                            urls.insightNew()
                                                                                        )
                                                                                    }}
                                                                                >
                                                                                    {item.sideAction.icon}
                                                                                </Button.Icon>
                                                                            )}
                                                                    </>
                                                                )}
                                                            </Button.Root>
                                                        </ListBox.Item>
                                                    )
                                                })}
                                            </ul>
                                        ))}
                                    </div>
                                </div>
                            </ListBox>
                        </ScrollableShadows>

                        <div className="border-b border-primary h-px " />

                        {/* 
                            Extra padding to compensate for dev mode debug notice... 
                            not sure how better to do this other than lower the notices z-index.. 
                        */}
                        <div className={`pt-1 px-1 flex flex-col gap-px ${isDev ? 'pb-10' : 'pb-2'}`}>
                            {visibleTabs.includes(SidePanelTab.Activation) && (
                                <Button.Root
                                    menuItem
                                    onClick={() =>
                                        sidePanelOpen && selectedTab === SidePanelTab.Activation
                                            ? closeSidePanel()
                                            : openSidePanel(SidePanelTab.Activation)
                                    }
                                    data-attr="activation-button"
                                >
                                    <Button.Icon size={isLayoutNavCollapsed ? 'lg' : 'base'}>
                                        <SidePanelActivationIcon size={isLayoutNavCollapsed ? 20 : 16} />
                                    </Button.Icon>
                                    {!isLayoutNavCollapsed && <Button.Label menuItem>Quick start</Button.Label>}
                                </Button.Root>
                            )}
                            <Button.Root menuItem to={urls.toolbarLaunch()} data-attr={Scene.ToolbarLaunch}>
                                <Button.Icon size={isLayoutNavCollapsed ? 'lg' : 'base'}>
                                    <IconToolbar />
                                </Button.Icon>
                                {!isLayoutNavCollapsed && <Button.Label menuItem>Toolbar</Button.Label>}
                            </Button.Root>

                            <Button.Root menuItem to={urls.settings('project')} data-attr={Scene.Settings}>
                                <Button.Icon size={isLayoutNavCollapsed ? 'lg' : 'base'}>
                                    <IconGear />
                                </Button.Icon>
                                {!isLayoutNavCollapsed && <Button.Label menuItem>Settings</Button.Label>}
                            </Button.Root>

                            <Popover
                                overlay={<AccountPopoverOverlay />}
                                visible={isAccountPopoverOpen}
                                onClickOutside={closeAccountPopover}
                                placement="right-end"
                                className="min-w-70"
                            >
                                <Button.Root menuItem active={isAccountPopoverOpen} onClick={toggleAccountPopover}>
                                    <Button.Icon size={isLayoutNavCollapsed ? 'lg' : 'base'}>
                                        <ProfilePicture
                                            user={user}
                                            size="sm"
                                            className={!isLayoutNavCollapsed ? 'mr-1' : ''}
                                        />
                                    </Button.Icon>
                                    {!isLayoutNavCollapsed && (
                                        <>
                                            <Button.Label menuItem>
                                                {user?.first_name ? (
                                                    <span>{user?.first_name}</span>
                                                ) : (
                                                    <span>{user?.email}</span>
                                                )}
                                            </Button.Label>
                                            <Button.Icon customIconSize>
                                                <IconChevronRight className="size-3 text-secondary" />
                                            </Button.Icon>
                                        </>
                                    )}
                                </Button.Root>
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
                        />
                    )}
                </nav>

                <div
                    className={cn(
                        panelStyles({
                            isLayoutPanelVisible,
                        })
                    )}
                >
                    {children}
                </div>
            </div>
        </>
    )
}
