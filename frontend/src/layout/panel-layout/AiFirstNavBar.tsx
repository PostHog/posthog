import { Collapsible } from '@base-ui/react/collapsible'
import { Menubar } from '@base-ui/react/menubar'
import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconChevronRight, IconClock, IconHome, IconNotification, IconSearch, IconSparkles } from '@posthog/icons'

import { NewAccountMenu } from 'lib/components/Account/NewAccountMenu'
import { RenderKeybind } from 'lib/components/AppShortcuts/AppShortcutMenu'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { commandLogic } from 'lib/components/Command/commandLogic'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { cn } from 'lib/utils/css-classes'
import { sceneLogic } from 'scenes/sceneLogic'
import { urls } from 'scenes/urls'

import { AppsMenu } from '~/layout/panel-layout/ai-first/AppsMenu'
import { DataMenu } from '~/layout/panel-layout/ai-first/DataMenu'
import { FilesMenu } from '~/layout/panel-layout/ai-first/FilesMenu'
import { RecentsMenu } from '~/layout/panel-layout/ai-first/RecentsMenu'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { ProjectTree } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { ActivityTab } from '~/types'

import { navigation3000Logic } from '../navigation-3000/navigationLogic'
import { NavBarFooter } from './NavBarFooter'

const navBarStyles = cva({
    base: 'flex flex-col max-h-screen min-h-screen bg-surface-tertiary z-[var(--z-layout-navbar)] relative border-r lg:border-r-transparent',
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

function SectionChevron({ open }: { open: boolean }): JSX.Element {
    return (
        <IconChevronRight
            className={cn(
                'size-3 text-tertiary opacity-0 group-hover:opacity-100 transition-all duration-150',
                open && 'rotate-90'
            )}
        />
    )
}

function SectionTrigger({
    label,
    open,
    isCollapsed,
}: {
    label: string
    open: boolean
    isCollapsed: boolean
}): JSX.Element {
    return (
        <Collapsible.Trigger
            className={cn('flex items-center w-full py-1 cursor-pointer group pl-2', isCollapsed && 'px-px')}
        >
            <Label
                intent="menu"
                className={cn(
                    'text-xxs text-tertiary text-left group-hover:text-primary mr-1',
                    isCollapsed && 'text-[7px] m-0 w-full text-center'
                )}
            >
                {label}
            </Label>
            {!isCollapsed && <SectionChevron open={open} />}
        </Collapsible.Trigger>
    )
}

export function AiFirstNavBar(): JSX.Element {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { toggleLayoutNavCollapsed, toggleNavSection } = useActions(panelLayoutLogic)
    const { isLayoutPanelVisible, isLayoutNavCollapsed, expandedNavSections } = useValues(panelLayoutLogic)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { firstTabIsActive } = useValues(sceneLogic)
    const { toggleCommand } = useActions(commandLogic)

    return (
        <div className="flex gap-0 relative">
            <nav
                className={cn(
                    navBarStyles({
                        isLayoutNavCollapsed,
                        isMobileLayout,
                    }),
                    isLayoutNavCollapsed && 'gap-px'
                )}
                ref={containerRef}
            >
                <div
                    className={cn(
                        'flex justify-between items-center',
                        isLayoutNavCollapsed ? 'justify-center' : 'h-[var(--scene-layout-header-height)]'
                    )}
                >
                    <div
                        className={cn('flex gap-1 rounded-md w-full px-1', {
                            'flex-col items-center pt-2': isLayoutNavCollapsed,
                        })}
                    >
                        <NewAccountMenu isLayoutNavCollapsed={isLayoutNavCollapsed} />

                        <ButtonPrimitive
                            iconOnly
                            tooltip={
                                <>
                                    <span>Search</span> <RenderKeybind keybind={[keyBinds.search]} />
                                </>
                            }
                            onClick={() => toggleCommand()}
                        >
                            <IconSearch className="size-4 text-secondary" />
                        </ButtonPrimitive>
                    </div>
                </div>

                <div className="z-[var(--z-main-nav)] flex flex-col flex-1 overflow-y-auto">
                    <ScrollableShadows
                        className={cn('flex-1', { 'rounded-tr': !isLayoutPanelVisible && !firstTabIsActive })}
                        innerClassName="overflow-y-auto overflow-x-hidden"
                        direction="vertical"
                        styledScrollbars
                    >
                        <div className={cn('flex flex-col gap-px px-1', isLayoutNavCollapsed && 'items-center')}>
                            <Link
                                tooltip={isLayoutNavCollapsed ? 'PostHog AI' : undefined}
                                tooltipPlacement="right"
                                to={urls.ai()}
                                buttonProps={{
                                    menuItem: !isLayoutNavCollapsed,
                                    iconOnly: isLayoutNavCollapsed,
                                }}
                            >
                                <IconSparkles className="size-4 text-secondary" />
                                {!isLayoutNavCollapsed && <span className="flex-1 text-left">PostHog AI</span>}
                            </Link>
                        </div>

                        <Collapsible.Root
                            open={expandedNavSections.project ?? true}
                            onOpenChange={() => toggleNavSection('project')}
                            className="px-1 mt-2"
                        >
                            <SectionTrigger
                                label="Project"
                                open={expandedNavSections.project ?? true}
                                isCollapsed={isLayoutNavCollapsed}
                            />
                            <Collapsible.Panel
                                className={cn('flex flex-col gap-px', isLayoutNavCollapsed && 'items-center')}
                            >
                                <Link
                                    buttonProps={{
                                        menuItem: !isLayoutNavCollapsed,
                                        iconOnly: isLayoutNavCollapsed,
                                    }}
                                    to={urls.projectRoot()}
                                    tooltip={isLayoutNavCollapsed ? 'Home' : undefined}
                                    tooltipPlacement="right"
                                >
                                    <IconHome className="size-4 text-secondary" />
                                    {!isLayoutNavCollapsed && <span className="flex-1 text-left">Home</span>}
                                </Link>

                                <Link
                                    buttonProps={{
                                        menuItem: !isLayoutNavCollapsed,
                                        iconOnly: isLayoutNavCollapsed,
                                    }}
                                    tooltip={isLayoutNavCollapsed ? 'Inbox' : undefined}
                                    tooltipPlacement="right"
                                    to={urls.inbox()}
                                >
                                    <IconNotification className="size-4 text-secondary" />
                                    {!isLayoutNavCollapsed && <span className="flex-1 text-left">Inbox</span>}
                                </Link>

                                <Link
                                    buttonProps={{
                                        menuItem: !isLayoutNavCollapsed,
                                        iconOnly: isLayoutNavCollapsed,
                                    }}
                                    tooltip={isLayoutNavCollapsed ? 'Activity' : undefined}
                                    tooltipPlacement="right"
                                    to={urls.activity(ActivityTab.ExploreEvents)}
                                >
                                    <IconClock className="size-4 text-secondary" />
                                    {!isLayoutNavCollapsed && <span className="flex-1 text-left">Activity</span>}
                                </Link>

                                <Menubar
                                    orientation="vertical"
                                    modal={false}
                                    className={cn('flex flex-col gap-px', isLayoutNavCollapsed && 'items-center')}
                                >
                                    <AppsMenu isCollapsed={isLayoutNavCollapsed} />
                                    <DataMenu isCollapsed={isLayoutNavCollapsed} />
                                    <FilesMenu isCollapsed={isLayoutNavCollapsed} />
                                    <RecentsMenu isCollapsed={isLayoutNavCollapsed} />
                                </Menubar>
                            </Collapsible.Panel>
                        </Collapsible.Root>

                        <Collapsible.Root
                            open={expandedNavSections.favorites ?? true}
                            onOpenChange={() => toggleNavSection('favorites')}
                            className="px-1 mt-2"
                        >
                            <SectionTrigger
                                label="Starred"
                                open={expandedNavSections.favorites ?? true}
                                isCollapsed={isLayoutNavCollapsed}
                            />
                            <Collapsible.Panel
                                className={cn(
                                    '-ml-1 w-[calc(100%+(var(--spacing)*2))]',
                                    isLayoutNavCollapsed ? 'items-center' : ''
                                )}
                            >
                                <ProjectTree
                                    root="shortcuts://"
                                    onlyTree
                                    treeSize={isLayoutNavCollapsed ? 'narrow' : 'default'}
                                />
                            </Collapsible.Panel>
                        </Collapsible.Root>
                    </ScrollableShadows>

                    <div className="border-b border-primary h-px" />

                    <NavBarFooter isLayoutNavCollapsed={isLayoutNavCollapsed} />
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
                        className={cn('top-[calc(var(--scene-layout-header-height)+7px)] right-[-1px] bottom-4', {
                            'top-[var(--scene-layout-header-height)]': firstTabIsActive,
                            'top-0': isLayoutPanelVisible,
                        })}
                        offset={0}
                    />
                )}
            </nav>
        </div>
    )
}
