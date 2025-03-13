import {
    IconBolt,
    IconChevronRight,
    IconClock,
    IconFolderOpen,
    IconPeople,
    IconPlusSmall,
    IconSearch,
} from '@posthog/icons'
import { cva } from 'class-variance-authority'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { IconWrapper } from 'lib/ui/IconWrapper/IconWrapper'
import { cn } from 'lib/utils/css-classes'
import { useRef } from 'react'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { panelLayoutLogic, PanelLayoutNavItem } from '~/layout/panel-layout/panelLayoutLogic'

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
    const { showLayoutPanel, setActiveLayoutNavBarItem, clearActiveLayoutNavBarItem } = useActions(panelLayoutLogic)
    const { isLayoutPanelVisible, activeLayoutNavBarItem } = useValues(panelLayoutLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { navbarItems } = useValues(navigation3000Logic)
    const { activeScene } = useValues(sceneLogic)

    function handleClick(item: PanelLayoutNavItem): void {
        if (activeLayoutNavBarItem !== item) {
            setActiveLayoutNavBarItem(item)
            showLayoutPanel(true)
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
                        <ScrollableShadows innerClassName="overflow-y-auto px-2 " direction="vertical" className="pb-2">
                            <LemonButton
                                className={cn(
                                    'hover:bg-fill-highlight-100',
                                    activeLayoutNavBarItem === 'project' && 'bg-fill-highlight-50'
                                )}
                                icon={
                                    <IconWrapper>
                                        <IconFolderOpen className="stroke-[1.2]" />
                                    </IconWrapper>
                                }
                                onClick={() => handleClick('project')}
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
                                    activeLayoutNavBarItem === 'persons' && 'bg-fill-highlight-50'
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
                                onClick={() => handleClick('persons')}
                            >
                                <span>People</span>
                            </LemonButton>

                            <LemonButton
                                className={cn(
                                    'hover:bg-fill-highlight-100',
                                    activeLayoutNavBarItem === 'activity' && 'bg-fill-highlight-50'
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
                                    setActiveLayoutNavBarItem('activity')
                                }}
                            >
                                <span>Activity</span>
                            </LemonButton>

                            <div className="border-b border-secondary h-px" />

                            <div className="pt-3">
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
                                                        clearActiveLayoutNavBarItem()
                                                        item.onClick?.()
                                                    }}
                                                >
                                                    {item.label}
                                                </LemonButton>
                                            )
                                        )}
                                    </ul>
                                ))}
                            </div>
                        </ScrollableShadows>
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
