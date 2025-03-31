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
import clsx from 'clsx'
import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Popover } from 'lib/lemon-ui/Popover'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonGroupPrimitive, ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ListBox } from 'lib/ui/ListBox/ListBox'
import { cn } from 'lib/utils/css-classes'
import { useRef } from 'react'
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
    const { showLayoutPanel, setActivePanelIdentifier, clearActivePanelIdentifier } = useActions(panelLayoutLogic)
    const { isLayoutPanelVisible, activePanelIdentifier, mainContentRef, isLayoutPanelPinned } =
        useValues(panelLayoutLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { navbarItems } = useValues(navigation3000Logic)
    const { closeAccountPopover, toggleAccountPopover } = useActions(navigationLogic)
    const { user } = useValues(userLogic)
    const { isAccountPopoverOpen } = useValues(navigationLogic)
    const { visibleTabs, sidePanelOpen, selectedTab } = useValues(sidePanelLogic)
    const { openSidePanel, closeSidePanel } = useActions(sidePanelStateLogic)

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
                    className={clsx(
                        'relative flex flex-col max-h-screen min-h-screen bg-surface-tertiary z-[var(--z-project-panel-layout)] w-[250px] border-r border-primary'
                    )}
                    ref={containerRef}
                >
                    <div className="flex justify-between p-1">
                        <OrganizationDropdownMenu />

                        <ButtonPrimitive
                            size="base"
                            iconOnly
                            onClick={() => toggleSearchBar()}
                            data-attr="search-button"
                        >
                            <IconSearch className="text-secondary" />
                        </ButtonPrimitive>
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
                                            <ButtonPrimitive
                                                menuItem
                                                active={item.id === 'Project' && isLayoutPanelVisible}
                                                data-attr={`menu-item-${item.identifier.toString().toLowerCase()}`}
                                            >
                                                <span className="text-tertiary">{item.icon}</span>
                                                <span className="truncate">{item.id}</span>
                                                {item.id === 'Project' && (
                                                    <span className="ml-auto">
                                                        <IconChevronRight className="size-3 text-secondary" />
                                                    </span>
                                                )}
                                            </ButtonPrimitive>
                                        </ListBox.Item>
                                    ))}
                                </div>

                                <div className="border-b border-primary h-px my-1" />

                                <div className="pt-1 px-1">
                                    <div className="flex justify-between items-center pl-2 pr-0 pb-2">
                                        <span className="text-xs font-semibold text-quaternary">Products</span>
                                    </div>
                                    <div className="flex flex-col gap-px">
                                        {navbarItems.map((section, index) => (
                                            <ul key={index} className="flex flex-col gap-px">
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
                                                            <ButtonGroupPrimitive menuItem fullWidth>
                                                                <ButtonPrimitive
                                                                    menuItem
                                                                    href={'to' in item ? item.to : undefined}
                                                                    data-attr={`menu-item-${item.identifier
                                                                        .toString()
                                                                        .toLowerCase()}`}
                                                                >
                                                                    <span className="text-tertiary">{item.icon}</span>
                                                                    <span className="truncate">{item.label}</span>

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
                                                                </ButtonPrimitive>
                                                                {item.sideAction &&
                                                                    item.identifier === 'SavedInsights' && (
                                                                        <ButtonPrimitive href={urls.insightNew()}>
                                                                            {item.sideAction.icon}
                                                                        </ButtonPrimitive>
                                                                    )}
                                                            </ButtonGroupPrimitive>
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

                        <div className="pt-1 px-1 pb-2 flex flex-col gap-px">
                            {visibleTabs.includes(SidePanelTab.Activation) && (
                                <ButtonPrimitive
                                    menuItem
                                    onClick={() =>
                                        sidePanelOpen && selectedTab === SidePanelTab.Activation
                                            ? closeSidePanel()
                                            : openSidePanel(SidePanelTab.Activation)
                                    }
                                    data-attr="activation-button"
                                >
                                    <SidePanelActivationIcon size={16} />
                                    Quick start
                                </ButtonPrimitive>
                            )}
                            <ButtonPrimitive menuItem href={urls.toolbarLaunch()} data-attr={Scene.ToolbarLaunch}>
                                <span className="text-tertiary">
                                    <IconToolbar />
                                </span>
                                <span className="truncate">Toolbar</span>
                            </ButtonPrimitive>

                            <ButtonPrimitive menuItem href={urls.settings('project')} data-attr={Scene.Settings}>
                                <span className="text-tertiary">
                                    <IconGear />
                                </span>
                                <span className="truncate">Settings</span>
                            </ButtonPrimitive>

                            <Popover
                                overlay={<AccountPopoverOverlay />}
                                visible={isAccountPopoverOpen}
                                onClickOutside={closeAccountPopover}
                                placement="right-end"
                                className="min-w-70"
                            >
                                <ButtonPrimitive menuItem active={isAccountPopoverOpen} onClick={toggleAccountPopover}>
                                    <ProfilePicture user={user} size="sm" className="mr-1" />
                                    {user?.first_name ? <span>{user?.first_name}</span> : <span>{user?.email}</span>}
                                    <IconChevronRight className="size-3 text-secondary" />
                                </ButtonPrimitive>
                            </Popover>
                        </div>
                    </div>
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
