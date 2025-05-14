import {
    IconCdCase,
    IconChevronRight,
    IconClock,
    IconDashboard,
    IconDatabase,
    IconFolderOpen,
    IconGear,
    IconHome,
    IconNotebook,
    IconPeople,
    IconPineapple,
    IconSearch,
    IconToolbar,
} from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
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
import { Shortcuts } from '~/layout/panel-layout/Shortcuts/Shortcuts'
import { SidePanelTab } from '~/types'

import { navigationLogic } from '../navigation/navigationLogic'
import { AccountPopoverOverlay } from '../navigation/TopBar/AccountPopover'
import { KeyboardShortcut } from '../navigation-3000/components/KeyboardShortcut'
import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { SidePanelActivationIcon } from '../navigation-3000/sidepanel/panels/activation/SidePanelActivation'
import { sidePanelLogic } from '../navigation-3000/sidepanel/sidePanelLogic'
import { sidePanelStateLogic } from '../navigation-3000/sidepanel/sidePanelStateLogic'
import { OrganizationDropdownMenu } from './OrganizationDropdownMenu'

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

export function PanelLayoutNavBar({ children }: { children: React.ReactNode }): JSX.Element {
    const { toggleSearchBar } = useActions(commandBarLogic)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const {
        showLayoutPanel,
        setActivePanelIdentifier,
        clearActivePanelIdentifier,
        toggleLayoutNavCollapsed,
        setVisibleSideAction,
        showLayoutNavBar,
    } = useActions(panelLayoutLogic)
    const {
        isLayoutPanelVisible,
        activePanelIdentifier,
        mainContentRef,
        isLayoutPanelPinned,
        isLayoutNavCollapsed,
        visibleSideAction,
        isLayoutNavbarVisible,
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
            tooltip:
                isLayoutPanelVisible && activePanelIdentifier === 'Project'
                    ? 'Close project tree'
                    : 'Open project tree',
        },
        {
            identifier: 'Recent',
            id: 'Recent',
            icon: <IconClock className="stroke-[1.2]" />,
            onClick: (e?: React.KeyboardEvent) => {
                if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                    handlePanelTriggerClick('Recent')
                }
            },
            showChevron: true,
            tooltip: isLayoutPanelVisible && activePanelIdentifier === 'Recent' ? 'Close recent' : 'Open recent',
        },
        ...(featureFlags[FEATURE_FLAGS.TREE_VIEW_PRODUCTS]
            ? [
                  {
                      identifier: 'Products',
                      id: 'Products',
                      icon: <IconCdCase />,
                      onClick: (e?: React.KeyboardEvent) => {
                          if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                              handlePanelTriggerClick('Products')
                          }
                      },
                      showChevron: true,
                      tooltip:
                          isLayoutPanelVisible && activePanelIdentifier === 'Products'
                              ? 'Close products'
                              : 'Open products',
                  },
              ]
            : []),
        ...(featureFlags[FEATURE_FLAGS.GAME_CENTER]
            ? [
                  {
                      identifier: 'Games',
                      id: 'Games',
                      icon: <IconPineapple />,
                      onClick: (e?: React.KeyboardEvent) => {
                          if (!e || e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
                              handlePanelTriggerClick('Games')
                          }
                      },
                      showChevron: true,
                      tooltip: isLayoutPanelVisible && activePanelIdentifier === 'Games' ? 'Close games' : 'Open games',
                  },
              ]
            : []),
        ...(featureFlags[FEATURE_FLAGS.TREE_VIEW_PRODUCTS]
            ? []
            : [
                  {
                      identifier: 'Dashboards',
                      id: 'Dashboards',
                      icon: <IconDashboard />,
                      to: urls.dashboards(),
                      onClick: () => {
                          handleStaticNavbarItemClick(urls.dashboards(), true)
                      },
                      tooltip: 'Dashboards',
                      tooltipDocLink: 'https://posthog.com/docs/product-analytics/dashboards',
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
                      tooltipDocLink: 'https://posthog.com/docs/notebooks',
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
                      tooltipDocLink: 'https://posthog.com/docs/data',
                  },
              ]),

        {
            identifier: 'PersonsManagement',
            id: featureFlags[FEATURE_FLAGS.TREE_VIEW_PRODUCTS]
                ? 'Persons'
                : featureFlags[FEATURE_FLAGS.B2B_ANALYTICS]
                ? 'Persons and cohorts'
                : 'Persons and groups',
            icon: <IconPeople />,
            to: urls.persons(),
            onClick: () => {
                handleStaticNavbarItemClick(urls.persons(), true)
            },
            tooltip: featureFlags[FEATURE_FLAGS.TREE_VIEW_PRODUCTS]
                ? 'Persons'
                : featureFlags[FEATURE_FLAGS.B2B_ANALYTICS]
                ? 'Persons and cohorts'
                : 'Persons and groups',
            tooltipDocLink: 'https://posthog.com/docs/data/persons',
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
                                            {item.showChevron ? (
                                                <ButtonPrimitive
                                                    active={activePanelIdentifier === item.id}
                                                    className="group"
                                                    menuItem={!isLayoutNavCollapsed}
                                                    iconOnly={isLayoutNavCollapsed}
                                                    tooltip={item.tooltip}
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
                                                            <span className="truncate">{item.id}</span>
                                                            <span className="ml-auto">
                                                                <IconChevronRight className="size-3 text-secondary" />
                                                            </span>
                                                        </>
                                                    )}
                                                </ButtonPrimitive>
                                            ) : (
                                                <Link
                                                    data-attr={`menu-item-${item.identifier.toString().toLowerCase()}`}
                                                    buttonProps={{
                                                        menuItem: !isLayoutNavCollapsed,
                                                        className: 'group',
                                                        iconOnly: isLayoutNavCollapsed,
                                                    }}
                                                    to={item.to}
                                                    tooltip={item.tooltip}
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
                                                        <span className="truncate">{item.id}</span>
                                                    )}
                                                </Link>
                                            )}
                                        </ListBox.Item>
                                    ))}
                                </div>

                                <div className="border-b border-primary h-px my-1" />

                                {featureFlags[FEATURE_FLAGS.TREE_VIEW_PRODUCTS] ? (
                                    <div className={!isLayoutNavCollapsed ? 'pt-1' : ''}>
                                        <Shortcuts />
                                    </div>
                                ) : (
                                    <div className={`px-1 ${!isLayoutNavCollapsed ? 'pt-1' : ''}`}>
                                        {!isLayoutNavCollapsed && (
                                            <div className="flex justify-between items-center pl-2 pr-0 pb-2">
                                                <span className="text-xs font-semibold text-quaternary">Products</span>
                                            </div>
                                        )}
                                        <div
                                            className={`flex flex-col gap-px ${
                                                isLayoutNavCollapsed ? 'items-center' : ''
                                            }`}
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
                                                            <ButtonGroupPrimitive menuItem fullWidth>
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
                                                                    <Link
                                                                        data-attr={`menu-item-${item.identifier
                                                                            .toString()
                                                                            .toLowerCase()}`}
                                                                        buttonProps={{
                                                                            menuItem: !isLayoutNavCollapsed,
                                                                            className:
                                                                                'group data-[focused=true]:bg-fill-button-tertiary-hover',
                                                                            hasSideActionRight:
                                                                                item.sideAction && !isLayoutNavCollapsed
                                                                                    ? true
                                                                                    : false,
                                                                            iconOnly: isLayoutNavCollapsed,
                                                                        }}
                                                                        to={'to' in item ? item.to : undefined}
                                                                        tooltip={
                                                                            isLayoutNavCollapsed
                                                                                ? item.label
                                                                                : undefined
                                                                        }
                                                                        tooltipPlacement="right"
                                                                        tooltipDocLink={item.tooltipDocLink}
                                                                    >
                                                                        <span
                                                                            className={`flex text-tertiary group-hover:text-primary ${
                                                                                isLayoutNavCollapsed
                                                                                    ? '[&_svg]:size-5'
                                                                                    : ''
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
                                                                    </Link>
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
                                                                            <Link
                                                                                buttonProps={{
                                                                                    isSideActionRight: true,
                                                                                }}
                                                                                tooltip={item.sideAction.tooltip}
                                                                                tooltipPlacement="right"
                                                                                to={urls.insightNew()}
                                                                            >
                                                                                {item.sideAction.icon}
                                                                            </Link>
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
                                                                                    visibleSideAction ===
                                                                                    item.identifier
                                                                                }
                                                                                overlay={
                                                                                    item.sideAction.dropdown.overlay
                                                                                }
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
                                                                                    isSideActionRight
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
                                )}
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
                                    className={`flex text-tertiary group-hover:text-primary ${
                                        isLayoutNavCollapsed ? '[&_svg]:size-5' : ''
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
                        className="z-[var(--z-layout-navbar-under)] fixed inset-0 w-screen h-screen bg-[var(--bg-fill-highlight-100)] lg:bg-transparent"
                    />
                )}

                {isMobileLayout && isLayoutNavbarVisible && isLayoutPanelVisible && (
                    <div
                        onClick={() => {
                            showLayoutPanel(false)
                            clearActivePanelIdentifier()
                        }}
                        className="z-[var(--z-layout-navbar-over)] fixed inset-0 w-screen h-screen bg-[var(--bg-fill-highlight-100)] lg:bg-transparent"
                    />
                )}
            </div>
        </>
    )
}
