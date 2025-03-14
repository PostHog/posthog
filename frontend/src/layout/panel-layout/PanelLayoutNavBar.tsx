import {
    IconChevronRight,
    IconClock,
    IconFolderOpen,
    IconGear,
    IconPlusSmall,
    IconSearch,
    IconToolbar
} from '@posthog/icons'
import { cva } from 'class-variance-authority'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
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

import { router } from 'kea-router'
import { LemonTree, TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'
import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { navigationLogic } from '../navigation/navigationLogic'
import { AccountPopoverOverlay } from '../navigation/TopBar/AccountPopover'
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

type PanelItemIdentifier = 'project';

const panelItemIdentifiers: PanelItemIdentifier[] = ['project'];

export function PanelLayoutNavBar({ children }: { children: React.ReactNode }): JSX.Element {
    const { toggleSearchBar } = useActions(commandBarLogic)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { showLayoutPanel, toggleLayoutPanelPinned, setActivePanelIdentifier, clearActivePanelIdentifier } = useActions(panelLayoutLogic)
    const { isLayoutPanelVisible, activePanelIdentifier } = useValues(panelLayoutLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { navbarItems } = useValues(navigation3000Logic)
    const { activeScene } = useValues(sceneLogic)
    const { closeAccountPopover, toggleAccountPopover } = useActions(navigationLogic)
    const { user } = useValues(userLogic)
    const { isAccountPopoverOpen } = useValues(navigationLogic)

    const activeSceneLower = activeScene?.toLowerCase() as PanelLayoutNavIdentifier

    function handleTopNavBarItemClick(identifier: PanelItemIdentifier): void {
        if (activeSceneLower === identifier) {
            if (isLayoutPanelVisible) {
                showLayoutPanel(false)
                clearActivePanelIdentifier()
            } else {
                showLayoutPanel(true)
            }
        } else {
            setActivePanelIdentifier(identifier)
            showLayoutPanel(true)
        }
    }
    
    function handleBottomNavBarItemClick(): void {
        showLayoutPanel(false)
        toggleLayoutPanelPinned(false)
    }

    const treeData: TreeDataItem[] = [
        {
            id: 'project' as PanelLayoutNavIdentifier,
            name: 'Project',
            icon: <IconWrapper><IconFolderOpen className="stroke-[1.2]" /></IconWrapper>,
            onClick: () => {
                handleTopNavBarItemClick('project')
            },
            type: 'trigger',
            active: activePanelIdentifier === 'project',
            sideIcon: <IconWrapper><IconChevronRight /></IconWrapper>,
        },
        {
            id: 'search',
            name: 'Search',
            icon: <IconWrapper><IconSearch /></IconWrapper>,
            onClick: () => toggleSearchBar(),
            type: 'trigger',
        },
        // {
        //     id: 'data' as PanelLayoutNavIdentifier,
        //     name: 'Data',
        //     icon: <IconWrapper><IconBolt /></IconWrapper>,
        //     onClick: () => handleTopNavBarItemClick('data'),
        // },
        // {
        //     id: 'people' as PanelLayoutNavIdentifier,
        //     name: 'People',
        //     icon: <IconWrapper><IconPeople /></IconWrapper>,
        //     onClick: () => handleTopNavBarItemClick('persons'),
        // },
        {
            id: 'activity',
            name: 'Activity',
            icon: <IconWrapper><IconClock /></IconWrapper>,
            onClick: () => {
                router.actions.push(urls.activity())
            },
        },
        {
            id: 'separator',
            name: 'Separator',
            type: 'separator',
        },
        ...navbarItems.flatMap((section) => 
            section.map((item): TreeDataItem | null => {
                const identifier = item.identifier.toLowerCase()

                if (item.featureFlag && !featureFlags[item.featureFlag]) {
                    return null
                }

                // Hide certain items (they're handled in the top nav bar)
                if (identifier === 'activity') {
                    return null
                }

                // Create tree item
                const treeItem: TreeDataItem = {
                    id: identifier,
                    name: item.label,
                    icon: <IconWrapper>{item.icon}</IconWrapper>,
                    onClick: () => {
                        // Hide panel
                        showLayoutPanel(false)
                        // Unpin panel
                        toggleLayoutPanelPinned(false)
                        // Clear active panel identifier
                        clearActivePanelIdentifier()
                        // If item is a link, navigate to it
                        if ('to' in item && item.to) {
                            router.actions.push(item.to)
                        }
                    },
                }
                return treeItem
            }).filter((item): item is TreeDataItem => item !== null)
        )
    ]

    return (
        <>
            <div className="flex gap-0 relative">
                <nav
                    className={clsx(
                        'relative flex flex-col max-h-screen min-h-screen bg-surface-secondary z-[var(--z-project-panel-layout)] w-[250px] border-r border-primary'
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
                                alert('global "new" button which would let you create a bunch of new things')
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
                        <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" className="pb-2">
                            <div className="pb-3">
                            <LemonTree
                                className="px-0 py-1"
                                data={treeData}
                                defaultSelectedFolderOrNodeId={activeSceneLower}
                            />
                                {/* <LemonButton
                                    className={cn(
                                        'hover:bg-fill-highlight-100',
                                        activeIdentifier === 'project' && 'bg-fill-highlight-50'
                                    )}
                                    icon={
                                        <IconWrapper>
                                            <IconFolderOpen className="stroke-[1.2]" />
                                        </IconWrapper>
                                    }
                                    onClick={() => handleTopNavBarItemClick('project')}
                                    fullWidth
                                    size="small"
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
                                    className="hover:bg-fill-highlight-100"
                                    fullWidth
                                    disabledReason="Coming soon"
                                    icon={
                                        <IconWrapper>
                                            <IconBolt />
                                        </IconWrapper>
                                    }
                                    size="small"
                                    sideIcon={
                                        <IconWrapper size="sm">
                                            <IconChevronRight />
                                        </IconWrapper>
                                    }
                                >
                                    <span>Data</span>
                                </LemonButton>
                                <LemonButton
                                    className={cn(
                                        'hover:bg-fill-highlight-100',
                                        activeIdentifier === 'persons' && 'bg-fill-highlight-50'
                                    )}
                                    fullWidth
                                    icon={
                                        <IconWrapper>
                                            <IconPeople />
                                        </IconWrapper>
                                    }
                                    size="small"
                                    sideIcon={
                                        <IconWrapper size="sm">
                                            <IconChevronRight />
                                        </IconWrapper>
                                    }
                                    onClick={() => handleTopNavBarItemClick('persons')}
                                >
                                    <span>People</span>
                                </LemonButton>
                                <LemonButton
                                    className={cn(
                                        'hover:bg-fill-highlight-100',
                                        activeIdentifier === 'activity' && 'bg-fill-highlight-50'
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
                                        setActiveIdentifier('activity')
                                    }}
                                >
                                    <span>Activity</span>
                                </LemonButton> */}
                            </div>

                            <div className="border-b border-secondary h-px -mx-2" />

                            {/* <div className="pt-3">
                                <div className="flex justify-between items-center pt-1 pl-2 pr-0 pb-2">
                                    <span className="text-xs font-bold text-tertiary">Products</span>
                                </div>
                                {navbarItems.map((section, index) => (
                                    <ul key={index}>
                                        {section.map((item) =>
                                            item.featureFlag && !featureFlags[item.featureFlag] ? null : (
                                                <LemonButton
                                                    key={item.identifier}
                                                    className={cn(
                                                        'hover:bg-fill-highlight-100',
                                                        activeScene?.toLowerCase() === item.identifier.toLowerCase() &&
                                                            'bg-fill-highlight-50'
                                                    )}
                                                    icon={<IconWrapper>{item.icon}</IconWrapper>}
                                                    fullWidth
                                                    size="small"
                                                    to={'to' in item ? item.to : undefined}
                                                    onClick={() => {
                                                        handleBottomNavBarItemClick(item.identifier.toLowerCase() as PanelLayoutNavIdentifier)
                                                        item.onClick?.()
                                                    }}
                                                >
                                                    {item.label}
                                                </LemonButton>
                                            )
                                        )}
                                    </ul>
                                ))}
                            </div> */}
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
                                    handleBottomNavBarItemClick()
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
                                    handleBottomNavBarItemClick()
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
                                    <span>Hi{user?.first_name ? `, ${user?.first_name}` : ''}!</span>
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
