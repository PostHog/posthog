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
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Popover } from 'lib/lemon-ui/Popover'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
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
import { KeyboardShortcut } from '../navigation-3000/components/KeyboardShortcut'
import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { SidePanelActivationIcon } from '../navigation-3000/sidepanel/panels/activation/SidePanelActivation'
import { sidePanelLogic } from '../navigation-3000/sidepanel/sidePanelLogic'
import { sidePanelStateLogic } from '../navigation-3000/sidepanel/sidePanelStateLogic'
import { OrganizationDropdownMenu } from './OrganizationDropdownMenu'

const panelStyles = cva({
    base: 'z-[var(--z-layout-navbar)] h-screen left-0',
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
    const {
        showLayoutPanel,
        setActivePanelIdentifier,
        clearActivePanelIdentifier,
        toggleLayoutNavCollapsed,
        setVisibleSideAction,
    } = useActions(panelLayoutLogic)
    const {
        isLayoutPanelVisible,
        activePanelIdentifier,
        mainContentRef,
        isLayoutPanelPinned,
        isLayoutNavCollapsed,
        visibleSideAction,
    } = useValues(panelLayoutLogic)
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
            tooltip: 'Home',
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
            tooltip: isLayoutPanelVisible ? 'Close project tree' : 'Open project tree',
        },
        {
            identifier: 'Dashboards',
            id: 'Dashboards',
            icon: <IconDashboard />,
            to: urls.dashboards(),
            onClick: () => {
                handleStaticNavbarItemClick(urls.dashboards(), true)
            },
            tooltip: 'Dashboards',
        },
        {
            identifier: 'Notebooks',
            id: 'Notebooks',
            icon: <IconNotebook />,
            to: urls.notebooks(),
            onClick: () => {
                handleStaticNavbarItemClick(urls.notebooks(), true)
            },
            tooltip: 'Notebooks',
        },
        {
            identifier: 'DataManagement',
            id: 'Data management',
            icon: <IconDatabase />,
            to: urls.eventDefinitions(),
            onClick: () => {
                handleStaticNavbarItemClick(urls.eventDefinitions(), true)
            },
            tooltip: 'Data management',
        },
        {
            identifier: 'PersonsManagement',
            id: featureFlags[FEATURE_FLAGS.B2B_ANALYTICS] ? 'Persons and cohorts' : 'Persons and groups',
            icon: <IconPeople />,
            to: urls.persons(),
            onClick: () => {
                handleStaticNavbarItemClick(urls.persons(), true)
            },
            tooltip: featureFlags[FEATURE_FLAGS.B2B_ANALYTICS] ? 'Persons and cohorts' : 'Persons and groups',
        },
        {
            identifier: 'Activity',
            id: 'Activity',
            icon: <IconClock />,
            to: urls.activity(),
            onClick: () => {
                handleStaticNavbarItemClick(urls.activity(), true)
            },
            tooltip: 'Activity',
        },
    ]

    return (
        <>
            <div className="flex gap-0 relative">
                <nav
                    className={cn(
                        'relative flex flex-col max-h-screen min-h-screen bg-surface-tertiary z-[var(--z-layout-panel)] border-r border-primary',
                        {
                            'w-[var(--project-navbar-width-collapsed)]': isLayoutNavCollapsed,
                            'w-[var(--project-navbar-width)]': !isLayoutNavCollapsed,
                        }
                    )}
                    ref={containerRef}
                >
                    <div className={`flex justify-between p-1 ${isLayoutNavCollapsed ? 'justify-center' : ''}`}>
                        <OrganizationDropdownMenu />

                        {!isLayoutNavCollapsed && (
                            <ButtonPrimitive
                                size="base"
                                iconOnly
                                onClick={toggleSearchBar}
                                data-attr="search-button"
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
                                    className={`px-1 flex flex-col gap-px ${
                                        isLayoutNavCollapsed ? 'items-center' : ''
                                    }`}
                                >
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
                                            <ButtonPrimitive
                                                menuItem={!isLayoutNavCollapsed}
                                                active={item.id === 'Project' && isLayoutPanelVisible}
                                                data-attr={`menu-item-${item.identifier.toString().toLowerCase()}`}
                                                className="group"
                                                href={item.to}
                                                iconOnly={isLayoutNavCollapsed}
                                                tooltip={isLayoutNavCollapsed ? item.tooltip : undefined}
                                                tooltipPlacement="right"
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
                                                        <span className="truncate">{item.id}</span>
                                                        {item.id === 'Project' && (
                                                            <span className="ml-auto">
                                                                <IconChevronRight className="size-3 text-secondary" />
                                                            </span>
                                                        )}
                                                    </>
                                                )}
                                            </ButtonPrimitive>
                                        </ListBox.Item>
                                    ))}
                                </div>

                                <div className="border-b border-primary h-px my-1" />

                                <div className={`px-1 ${!isLayoutNavCollapsed ? 'pt-1' : ''}`}>
                                    {!isLayoutNavCollapsed && (
                                        <div className="flex justify-between items-center pl-2 pr-0 pb-2">
                                            <span className="text-xs font-semibold text-quaternary">Products</span>
                                        </div>
                                    )}
                                    <div
                                        className={`flex flex-col gap-px ${isLayoutNavCollapsed ? 'items-center' : ''}`}
                                    >
                                        {navbarItems.map((section, index) => (
                                            <ul key={index} className="flex flex-col gap-px ">
                                                {section.map((item) => {
                                                    if (filteredNavItemsIdentifiers.includes(item.identifier)) {
                                                        return null
                                                    }

                                                    const notEnabled =
                                                        item.featureFlag && !featureFlags[item.featureFlag]

                                                    return notEnabled ? null : (
                                                        <ButtonGroupPrimitive
                                                            menuItem
                                                            fullWidth
                                                            groupVariant="side-action-group"
                                                        >
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
                                                                <ButtonPrimitive
                                                                    menuItem={!isLayoutNavCollapsed}
                                                                    href={'to' in item ? item.to : undefined}
                                                                    data-attr={`menu-item-${item.identifier
                                                                        .toString()
                                                                        .toLowerCase()}`}
                                                                    className="group data-[focused=true]:bg-fill-button-tertiary-hover"
                                                                    sideActionLeft={
                                                                        item.sideAction && !isLayoutNavCollapsed
                                                                            ? true
                                                                            : false
                                                                    }
                                                                    iconOnly={isLayoutNavCollapsed}
                                                                    tooltip={
                                                                        isLayoutNavCollapsed ? item.label : undefined
                                                                    }
                                                                    tooltipPlacement="right"
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
                                                                            <span className="truncate">
                                                                                {item.label}
                                                                            </span>

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
                                                                        </>
                                                                    )}
                                                                </ButtonPrimitive>
                                                            </ListBox.Item>

                                                            {!isLayoutNavCollapsed &&
                                                                item.sideAction &&
                                                                item.identifier === 'SavedInsights' && (
                                                                    <ListBox.Item
                                                                        asChild
                                                                        key={item.identifier}
                                                                        onClick={() => {
                                                                            handleStaticNavbarItemClick(
                                                                                urls.insightNew(),
                                                                                false
                                                                            )
                                                                        }}
                                                                        onKeyDown={(e) => {
                                                                            if (e.key === 'Enter') {
                                                                                handleStaticNavbarItemClick(
                                                                                    urls.insightNew(),
                                                                                    true
                                                                                )
                                                                            }
                                                                        }}
                                                                    >
                                                                        <ButtonPrimitive
                                                                            sideActionRight
                                                                            tooltip={item.sideAction.tooltip}
                                                                            href={urls.insightNew()}
                                                                        >
                                                                            {item.sideAction.icon}
                                                                        </ButtonPrimitive>
                                                                    </ListBox.Item>
                                                                )}

                                                            {!isLayoutNavCollapsed &&
                                                                item.sideAction &&
                                                                item.identifier === 'Groups' &&
                                                                item.sideAction.dropdown?.overlay && (
                                                                    <ListBox.Item
                                                                        asChild
                                                                        key={`${item.identifier}-dropdown`}
                                                                    >
                                                                        <Popover
                                                                            visible={
                                                                                visibleSideAction === item.identifier
                                                                            }
                                                                            overlay={item.sideAction.dropdown.overlay}
                                                                            placement={
                                                                                item.sideAction.dropdown.placement
                                                                            }
                                                                            showArrow={false}
                                                                            onClickInside={() => {
                                                                                setVisibleSideAction('')
                                                                            }}
                                                                            onClickOutside={() => {
                                                                                setVisibleSideAction('')
                                                                            }}
                                                                        >
                                                                            <ButtonPrimitive
                                                                                sideActionRight
                                                                                active={
                                                                                    visibleSideAction ===
                                                                                    item.identifier
                                                                                }
                                                                                onClick={() => {
                                                                                    visibleSideAction ===
                                                                                    item.identifier
                                                                                        ? setVisibleSideAction('')
                                                                                        : setVisibleSideAction(
                                                                                              item.identifier
                                                                                          )
                                                                                }}
                                                                            >
                                                                                <IconChevronRight className="size-3 text-secondary" />
                                                                            </ButtonPrimitive>
                                                                        </Popover>
                                                                    </ListBox.Item>
                                                                )}
                                                        </ButtonGroupPrimitive>
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
                        <div
                            className={`pt-1 px-1 flex flex-col gap-px ${isLayoutNavCollapsed ? 'items-center' : ''} ${
                                isDev ? 'pb-10' : 'pb-2'
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
                            <ButtonPrimitive
                                menuItem={!isLayoutNavCollapsed}
                                onClick={() => {
                                    handleStaticNavbarItemClick(urls.toolbarLaunch(), true)
                                }}
                                href={urls.toolbarLaunch()}
                                data-attr={Scene.ToolbarLaunch}
                                tooltip={isLayoutNavCollapsed ? 'Toolbar' : undefined}
                                tooltipPlacement="right"
                                className="group"
                                iconOnly={isLayoutNavCollapsed}
                            >
                                <span
                                    className={`flex text-tertiary group-hover:text-primary ${
                                        isLayoutNavCollapsed ? '[&_svg]:size-5' : ''
                                    }`}
                                >
                                    <IconToolbar />
                                </span>
                                {!isLayoutNavCollapsed && 'Toolbar'}
                            </ButtonPrimitive>

                            <ButtonPrimitive
                                menuItem={!isLayoutNavCollapsed}
                                onClick={() => {
                                    handleStaticNavbarItemClick(urls.settings('project'), true)
                                }}
                                href={urls.settings('project')}
                                data-attr={Scene.Settings}
                                tooltip={isLayoutNavCollapsed ? 'Settings' : undefined}
                                tooltipPlacement="right"
                                className="group"
                                iconOnly={isLayoutNavCollapsed}
                            >
                                <span
                                    className={`flex text-tertiary group-hover:text-primary ${
                                        isLayoutNavCollapsed ? '[&_svg]:size-5' : ''
                                    }`}
                                >
                                    <IconGear />
                                </span>
                                {!isLayoutNavCollapsed && 'Settings'}
                            </ButtonPrimitive>

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
