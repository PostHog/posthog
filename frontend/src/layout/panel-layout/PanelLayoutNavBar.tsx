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
    IconPinFilled,
    IconSearch,
    IconToolbar,
} from '@posthog/icons'
import { cva } from 'class-variance-authority'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Popover } from 'lib/lemon-ui/Popover'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { IconWrapper } from 'lib/ui/IconWrapper/IconWrapper'
import { ListBox } from 'lib/ui/ListBox/ListBox'
import { cn } from 'lib/utils/css-classes'
import { useRef } from 'react'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { panelLayoutLogic, PanelLayoutNavIdentifier } from '~/layout/panel-layout/panelLayoutLogic'

import { breadcrumbsLogic } from '../navigation/Breadcrumbs/breadcrumbsLogic'
import { navigationLogic } from '../navigation/navigationLogic'
import { AccountPopoverOverlay } from '../navigation/TopBar/AccountPopover'
import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { OrganizationDropdownMenu } from './OrganizationDropdownMenu'

const panelStyles = cva('z-[var(--z-project-panel-layout)] h-screen left-0', {
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
    const { activeScene } = useValues(sceneLogic)
    const { closeAccountPopover, toggleAccountPopover } = useActions(navigationLogic)
    const { user } = useValues(userLogic)
    const { isAccountPopoverOpen } = useValues(navigationLogic)
    const { sceneBreadcrumbKeys } = useValues(breadcrumbsLogic)

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

                        <LemonButton
                            size="small"
                            type="tertiary"
                            tooltip="Search"
                            onClick={() => toggleSearchBar()}
                            icon={
                                <IconWrapper>
                                    <IconSearch />
                                </IconWrapper>
                            }
                        />
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
                                            <LemonButton
                                                className={cn(
                                                    activePanelIdentifier === item.identifier &&
                                                        'bg-fill-button-tertiary-active'
                                                )}
                                                icon={<IconWrapper>{item.icon}</IconWrapper>}
                                                fullWidth
                                                size="small"
                                                sideIcon={
                                                    item.showChevron ? (
                                                        <IconWrapper size="sm">
                                                            <IconChevronRight />
                                                        </IconWrapper>
                                                    ) : undefined
                                                }
                                                to={item.to}
                                            >
                                                <span>{item.id}</span>
                                                <span className="ml-auto">
                                                    {item.id === 'Project' &&
                                                        isLayoutPanelPinned &&
                                                        isLayoutPanelVisible && (
                                                            <IconWrapper size="sm">
                                                                <IconPinFilled />
                                                            </IconWrapper>
                                                        )}
                                                </span>
                                            </LemonButton>
                                        </ListBox.Item>
                                    ))}
                                </div>

                                <div className="border-b border-secondary h-px my-1" />

                                <div className="pt-1 px-1">
                                    <div className="flex justify-between items-center pl-2 pr-0 pb-2">
                                        <span className="text-xs font-bold text-tertiary">Products</span>
                                    </div>
                                    <div className="flex flex-col gap-px">
                                        {navbarItems.map((section, index) => (
                                            <ul key={index} className="flex flex-col gap-px">
                                                {section.map((item) => {
                                                    if (filteredNavItemsIdentifiers.includes(item.identifier)) {
                                                        return null
                                                    }
                                                    return item.featureFlag &&
                                                        !featureFlags[item.featureFlag] ? null : (
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
                                                            <LemonButton
                                                                key={item.identifier}
                                                                icon={<IconWrapper>{item.icon}</IconWrapper>}
                                                                sideIcon={
                                                                    item.tag ? (
                                                                        <LemonTag
                                                                            type={
                                                                                item.tag === 'alpha'
                                                                                    ? 'completion'
                                                                                    : item.tag === 'beta'
                                                                                    ? 'warning'
                                                                                    : 'success'
                                                                            }
                                                                            size="small"
                                                                            className="ml-2"
                                                                        >
                                                                            {item.tag.toUpperCase()}
                                                                        </LemonTag>
                                                                    ) : undefined
                                                                }
                                                                fullWidth
                                                                size="small"
                                                                // This makes it a link if it has a to
                                                                // we handle routing in the handleStaticNavbarItemClick function
                                                                to={'to' in item ? item.to : undefined}
                                                            >
                                                                {item.label}
                                                            </LemonButton>
                                                        </ListBox.Item>
                                                    )
                                                })}
                                            </ul>
                                        ))}
                                    </div>
                                </div>
                            </ListBox>
                        </ScrollableShadows>

                        <div className="border-b border-secondary h-px " />

                        <div className="pt-1 px-1 pb-2 flex flex-col gap-px">
                            <LemonButton
                                className={cn(
                                    (activeScene === Scene.ToolbarLaunch ||
                                        sceneBreadcrumbKeys.includes(Scene.ToolbarLaunch)) &&
                                        'bg-fill-button-tertiary-active'
                                )}
                                icon={
                                    <IconWrapper>
                                        <IconToolbar />
                                    </IconWrapper>
                                }
                                fullWidth
                                size="small"
                                to={urls.toolbarLaunch()}
                                onClick={() => {
                                    handleStaticNavbarItemClick(urls.toolbarLaunch(), false)
                                }}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                        handleStaticNavbarItemClick(urls.toolbarLaunch(), true)
                                    }
                                }}
                                active={
                                    activeScene === Scene.ToolbarLaunch ||
                                    sceneBreadcrumbKeys.includes(Scene.ToolbarLaunch)
                                }
                            >
                                Toolbar
                            </LemonButton>

                            <LemonButton
                                className={cn(
                                    (activeScene === Scene.Settings || sceneBreadcrumbKeys.includes(Scene.Settings)) &&
                                        'bg-fill-button-tertiary-active'
                                )}
                                icon={
                                    <IconWrapper>
                                        <IconGear />
                                    </IconWrapper>
                                }
                                to={urls.settings('project')}
                                onClick={() => {
                                    handleStaticNavbarItemClick(urls.settings('project'), false)
                                }}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') {
                                        handleStaticNavbarItemClick(urls.settings('project'), true)
                                    }
                                }}
                                fullWidth
                                size="small"
                                active={activeScene === Scene.Settings || sceneBreadcrumbKeys.includes(Scene.Settings)}
                            >
                                Settings
                            </LemonButton>

                            <Popover
                                overlay={<AccountPopoverOverlay />}
                                visible={isAccountPopoverOpen}
                                onClickOutside={closeAccountPopover}
                                placement="right-end"
                                className="min-w-70"
                            >
                                <LemonButton
                                    className={cn(isAccountPopoverOpen && 'bg-fill-button-tertiary-active')}
                                    fullWidth
                                    size="small"
                                    sideIcon={
                                        <IconWrapper size="sm">
                                            <IconChevronRight />
                                        </IconWrapper>
                                    }
                                    icon={<ProfilePicture user={user} size="sm" className="mr-1" />}
                                    title={`Hi${user?.first_name ? `, ${user?.first_name}` : ''}!`}
                                    onClick={toggleAccountPopover}
                                >
                                    {user?.first_name ? <span>{user?.first_name}</span> : <span>{user?.email}</span>}
                                </LemonButton>
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
