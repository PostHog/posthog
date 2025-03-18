import {
    IconChevronRight,
    IconClock,
    IconFolderOpen,
    IconGear,
    IconPlusSmall,
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
import { cn } from 'lib/utils/css-classes'
import { useRef } from 'react'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { panelLayoutLogic, PanelLayoutNavIdentifier } from '~/layout/panel-layout/panelLayoutLogic'

import { breadcrumbsLogic } from '../navigation/Breadcrumbs/breadcrumbsLogic'
import { navigationLogic } from '../navigation/navigationLogic'
import { AccountPopoverOverlay } from '../navigation/TopBar/AccountPopover'
import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { NavbarItem } from '../navigation-3000/types'
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
    const { isLayoutPanelVisible, activePanelIdentifier, mainContentRef } = useValues(panelLayoutLogic)
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

    function handleStaticNavbarItemClick(navbarItem: NavbarItem, isKeyboardAction = false): void {
        clearActivePanelIdentifier()
        showLayoutPanel(false)

        if (isKeyboardAction) {
            mainContentRef?.current?.focus()
        }
        if ('to' in navbarItem && navbarItem.to) {
            router.actions.push(navbarItem.to)
        }
    }

    return (
        <>
            <div className="flex gap-0 relative">
                <nav
                    className={clsx(
                        'relative flex flex-col max-h-screen min-h-screen bg-surface-tertiary z-[var(--z-project-panel-layout)] w-[250px] border-r border-primary'
                    )}
                    ref={containerRef}
                >
                    <div className="flex justify-between pt-1 pl-1 pr-2 pb-1">
                        <OrganizationDropdownMenu />

                        <LemonButton
                            size="small"
                            type="tertiary"
                            tooltip="Create new"
                            onClick={() =>
                                alert('global “new” button which would let you create a bunch of new things')
                            }
                            className="hover:bg-fill-highlight-100 shrink-0"
                            icon={
                                <IconWrapper>
                                    <IconPlusSmall />
                                </IconWrapper>
                            }
                        />
                    </div>

                    <div className="z-[var(--z-main-nav)] flex flex-col flex-1 overflow-y-auto pt-1">
                        <ScrollableShadows innerClassName="overflow-y-auto px-2 " direction="vertical">
                            <div className="pb-3">
                                <LemonButton
                                    className={cn(
                                        'hover:bg-fill-highlight-100',
                                        activePanelIdentifier === 'project' && 'bg-fill-highlight-50'
                                    )}
                                    icon={
                                        <IconWrapper>
                                            <IconFolderOpen className="stroke-[1.2]" />
                                        </IconWrapper>
                                    }
                                    onClick={() => handlePanelTriggerClick('project')}
                                    fullWidth
                                    size="small"
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter') {
                                            handlePanelTriggerClick('project')
                                        }
                                    }}
                                    sideIcon={
                                        <IconWrapper size="sm">
                                            <IconChevronRight />
                                        </IconWrapper>
                                    }
                                >
                                    <span>Project</span>
                                </LemonButton>
                                <LemonButton
                                    className="hover:bg-fill-highlight-100"
                                    fullWidth
                                    size="small"
                                    onClick={toggleSearchBar}
                                    icon={
                                        <IconWrapper>
                                            <IconSearch />
                                        </IconWrapper>
                                    }
                                >
                                    <span>Search</span>
                                </LemonButton>
                                <LemonButton
                                    className={cn(
                                        'hover:bg-fill-highlight-100',
                                        activePanelIdentifier === 'activity' && 'bg-fill-highlight-50'
                                    )}
                                    fullWidth
                                    icon={
                                        <IconWrapper>
                                            <IconClock />
                                        </IconWrapper>
                                    }
                                    size="small"
                                    to={urls.activity()}
                                    onClick={() => {
                                        if (isLayoutPanelVisible) {
                                            showLayoutPanel(false)
                                        }
                                    }}
                                >
                                    <span>Activity</span>
                                </LemonButton>
                            </div>

                            <div className="border-b border-secondary h-px -mx-2" />

                            <div className="pt-3">
                                <div className="flex justify-between items-center pt-1 pl-2 pr-0 pb-2">
                                    <span className="text-xs font-bold text-tertiary">Products</span>
                                </div>
                                {navbarItems.map((section, index) => (
                                    <ul key={index}>
                                        {section.map((item) => {
                                            if (item.identifier === 'Activity') {
                                                return null
                                            }
                                            return item.featureFlag && !featureFlags[item.featureFlag] ? null : (
                                                <LemonButton
                                                    key={item.identifier}
                                                    className={cn(
                                                        'hover:bg-fill-highlight-100',
                                                        activeScene === item.identifier && 'bg-fill-highlight-50'
                                                    )}
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
                                                    to={'to' in item ? item.to : undefined}
                                                    // we handle routing in the handleStaticNavbarItemClick function
                                                    onClick={() => {
                                                        handleStaticNavbarItemClick(item, false)
                                                    }}
                                                    // If enter, focus the main content
                                                    onKeyDown={(e) => {
                                                        if (e.key === 'Enter') {
                                                            handleStaticNavbarItemClick(item, true)
                                                        }
                                                    }}
                                                    active={
                                                        activePanelIdentifier === item.identifier ||
                                                        sceneBreadcrumbKeys.includes(item.identifier)
                                                    }
                                                >
                                                    {item.label}
                                                </LemonButton>
                                            )
                                        })}
                                    </ul>
                                ))}
                            </div>
                        </ScrollableShadows>

                        <div className="border-b border-secondary h-px" />

                        <div className="pt-3 px-2">
                            <div className="flex justify-between items-center pt-1 pl-2 pr-0 pb-2">
                                <span className="text-xs font-bold text-tertiary">Settings & tools</span>
                            </div>
                            <LemonButton
                                className="hover:bg-fill-highlight-100"
                                icon={
                                    <IconWrapper>
                                        <IconToolbar />
                                    </IconWrapper>
                                }
                                fullWidth
                                size="small"
                                to={urls.toolbarLaunch()}
                                onClick={() => {
                                    clearActivePanelIdentifier()
                                }}
                            >
                                Toolbar
                            </LemonButton>

                            {/* TODO: add other things from navbarBottom */}

                            <LemonButton
                                className="hover:bg-fill-highlight-100"
                                icon={
                                    <IconWrapper>
                                        <IconGear />
                                    </IconWrapper>
                                }
                                fullWidth
                                size="small"
                                to={urls.settings('project')}
                                onClick={() => {
                                    clearActivePanelIdentifier()
                                }}
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
                                    <span>{user?.first_name ? <span>{user?.first_name}</span> : null}</span>
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
