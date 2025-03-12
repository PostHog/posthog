import { IconBolt, IconChevronRight, IconClock, IconGear, IconPeople, IconPlus, IconSearch } from '@posthog/icons'
import { cva } from 'class-variance-authority'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { IconCircleDashed, IconFolderOpen } from 'lib/lemon-ui/LemonTree/LemonTreeUtils'
import { cn } from 'lib/utils/css-classes'
import { useRef } from 'react'
import { urls } from 'scenes/urls'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

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
    const { theme } = useValues(themeLogic)
    const { toggleSearchBar } = useActions(commandBarLogic)
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { showLayoutPanel, setActiveLayoutNavBarItem } = useActions(panelLayoutLogic)
    const { isLayoutPanelVisible, activeLayoutNavBarItem } = useValues(panelLayoutLogic)

    return (
        <>
            <div className="flex gap-0 relative">
                <nav
                    className={clsx(
                        'relative flex flex-col max-h-screen min-h-screen bg-surface-tertiary z-[var(--z-project-panel-layout)] w-[250px] border-r border-primary'
                    )}
                    ref={containerRef}
                >
                    <div className="flex justify-between pt-1 pl-1 pr-2 pb-2">
                        <OrganizationDropdownMenu />

                        <LemonButton
                            size="small"
                            type="tertiary"
                            tooltip="Create new"
                            onClick={() =>
                                alert('global “new” button which would let you create a bunch of new things')
                            }
                            className="hover:bg-fill-highlight-100 shrink-0"
                            icon={<IconPlus className="size-4" />}
                        />
                    </div>

                    <div
                        className="z-[var(--z-main-nav)] flex flex-col flex-1 overflow-y-auto"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={theme?.sidebarStyle}
                    >
                        <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical" className="px-2 pb-2">
                            <LemonButton
                                className={cn(
                                    'hover:bg-fill-highlight-100',
                                    activeLayoutNavBarItem === 'project' && 'bg-fill-highlight-50'
                                )}
                                icon={<IconFolderOpen className="size-5 stroke-[1.2]" />}
                                onClick={() => {
                                    showLayoutPanel(!isLayoutPanelVisible)
                                    if (activeLayoutNavBarItem !== 'project') {
                                        setActiveLayoutNavBarItem('project')
                                    }
                                }}
                                fullWidth
                                size="small"
                                sideIcon={<IconChevronRight className="size-4" />}
                            >
                                <span>Project</span>
                            </LemonButton>

                            <LemonButton
                                className="hover:bg-fill-highlight-100"
                                fullWidth
                                size="small"
                                onClick={toggleSearchBar}
                                icon={<IconSearch className="size-5" />}
                            >
                                <span>Search</span>
                            </LemonButton>

                            <LemonButton
                                className="hover:bg-fill-highlight-100"
                                fullWidth
                                icon={<IconBolt className="size-5" />}
                                size="small"
                                sideIcon={<IconChevronRight className="size-4" />}
                            >
                                <span>Data</span>
                            </LemonButton>

                            <LemonButton
                                className="hover:bg-fill-highlight-100"
                                fullWidth
                                icon={<IconPeople className="size-5" />}
                                size="small"
                                sideIcon={<IconChevronRight className="size-4" />}
                            >
                                <span>People</span>
                            </LemonButton>

                            <LemonButton
                                className="hover:bg-fill-highlight-100"
                                fullWidth
                                icon={<IconPeople className="size-5" />}
                                size="small"
                                sideIcon={<IconChevronRight className="size-4" />}
                            >
                                <span>Products</span>
                            </LemonButton>

                            <LemonButton
                                className={cn(
                                    'hover:bg-fill-highlight-100',
                                    activeLayoutNavBarItem === 'activity' && 'bg-fill-highlight-50'
                                )}
                                fullWidth
                                icon={<IconClock className="size-5" />}
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

                            <LemonButton
                                className="hover:bg-fill-highlight-100"
                                fullWidth
                                icon={<IconCircleDashed className="size-5" />}
                                size="small"
                                sideIcon={<IconChevronRight className="size-4" />}
                            >
                                <span>Quick start</span>
                            </LemonButton>
                        </ScrollableShadows>

                        <div className="border-b border-secondary h-px" />

                        <div className="px-2 pt-3">
                            <div className="flex justify-between items-center pt-1 pl-2 pr-0 pb-2">
                                <span className="text-xs font-bold text-tertiary">Shortcuts</span>

                                <div className="relative">
                                    <LemonButton
                                        className="hover:bg-fill-highlight-100 absolute right-0 top-1/2 -translate-y-1/2"
                                        size="small"
                                        onClick={() => alert('new organization')}
                                        icon={<IconGear className="size-4" />}
                                    />
                                </div>
                            </div>

                            <ScrollableShadows innerClassName="overflow-y-auto" direction="vertical">
                                <LemonButton
                                    className="hover:bg-fill-highlight-100"
                                    icon={<IconFolderOpen className="size-5 stroke-[1.2]" />}
                                    fullWidth
                                    size="small"
                                    sideIcon={<IconChevronRight className="size-4" />}
                                >
                                    <span>Project</span>
                                </LemonButton>
                            </ScrollableShadows>
                        </div>
                        {/* <NavbarBottom /> */}
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
