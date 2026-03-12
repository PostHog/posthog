import { Tabs } from '@base-ui/react/tabs'
import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { lazy, Suspense, useRef } from 'react'

import { IconApps, IconSearch, IconSparkles } from '@posthog/icons'

import { NewAccountMenu } from 'lib/components/Account/NewAccountMenu'
import { RenderKeybind } from 'lib/components/AppShortcuts/AppShortcutMenu'
import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { commandLogic } from 'lib/components/Command/commandLogic'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Collapsible } from 'lib/ui/Collapsible/Collapsible'
import { Label } from 'lib/ui/Label/Label'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'
import { sceneLogic } from 'scenes/sceneLogic'

import { NavExperimentTab, panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'

import { navigation3000Logic } from '../../navigation-3000/navigationLogic'
import { NavBarFooter } from '../NavBarFooter'
import { NavTabBrowse } from './tabs/NavTabBrowse'
const NavTabChat = lazy(() => import('./tabs/NavTabChat').then((m) => ({ default: m.NavTabChat })))

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

export function SectionTrigger({
    label,
    isCollapsed,
    icon,
}: {
    label: string
    isCollapsed: boolean
    icon: React.ReactNode
}): JSX.Element {
    return (
        <Collapsible.Trigger
            className={cn(
                'flex items-center py-1 cursor-pointer group pl-2 sticky top-0 bg-surface-tertiary z-10 -mx-1 px-2 w-[calc(100%+(var(--spacing)*2))]',
                isCollapsed && 'mx-0 w-full px-px'
            )}
        >
            <Label
                intent="menu"
                className={cn(
                    'text-xxs text-tertiary text-left group-hover:text-primary mr-1',
                    isCollapsed && 'text-[7px] m-0 w-full text-center'
                )}
            >
                {icon && !isCollapsed && <span className="size-3 mr-1">{icon}</span>}
                {label}
            </Label>
        </Collapsible.Trigger>
    )
}

const TAB_CONFIG: { id: NavExperimentTab; label: string; icon: JSX.Element }[] = [
    { id: 'home', label: 'Browse', icon: <IconApps /> },
    { id: 'chat', label: 'Chat', icon: <IconSparkles className="text-ai" /> },
]

export function Nav({ children }: { children?: React.ReactNode }): JSX.Element {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { toggleLayoutNavCollapsed, setNavExperimentTab } = useActions(panelLayoutLogic)
    const { isLayoutPanelVisible, isLayoutNavCollapsed, navExperimentActiveTab } = useValues(panelLayoutLogic)
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
                        className={cn('flex gap-1 rounded-md w-full px-2 pt-2 pb-1', {
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

                <Tabs.Root
                    className="z-[var(--z-main-nav)] flex flex-col flex-1 overflow-hidden"
                    value={navExperimentActiveTab}
                    onValueChange={(value) => setNavExperimentTab(value as NavExperimentTab)}
                    orientation={isLayoutNavCollapsed ? 'vertical' : 'horizontal'}
                >
                    <>
                        <Tabs.List
                            className={cn(
                                'relative flex items-center gap-1 shrink-0 z-0 pb-2 pt-1 px-2',
                                isLayoutNavCollapsed && 'flex-col justify-center'
                            )}
                        >
                            {TAB_CONFIG.map((tab) => (
                                <Tabs.Tab
                                    key={tab.id}
                                    value={tab.id}
                                    render={(props) => (
                                        <ButtonPrimitive
                                            {...props}
                                            className={cn(
                                                'group data-[composite-item-active]:bg-fill-button-tertiary-active w-1/2 justify-center',
                                                isLayoutNavCollapsed && 'w-full'
                                            )}
                                            data-attr={`nav-tab-${tab.id}`}
                                            iconOnly={isLayoutNavCollapsed}
                                        >
                                            <span
                                                className={cn(
                                                    'flex size-4',
                                                    navExperimentActiveTab === tab.id
                                                        ? 'text-primary'
                                                        : 'text-tertiary group-hover:text-primary'
                                                )}
                                            >
                                                {tab.icon}
                                            </span>

                                            {!isLayoutNavCollapsed && (
                                                <span
                                                    className={cn(
                                                        'text-xs',
                                                        navExperimentActiveTab === tab.id
                                                            ? 'text-primary'
                                                            : 'text-tertiary group-hover:text-primary'
                                                    )}
                                                >
                                                    {tab.label}
                                                </span>
                                            )}
                                        </ButtonPrimitive>
                                    )}
                                />
                            ))}
                        </Tabs.List>

                        <div className="h-px bg-border-primary -mx-1 w-[calc(100%+var(--spacing)*4)]" />
                    </>

                    <div className="flex-1 overflow-hidden relative">
                        <Tabs.Panel value="home" className="absolute inset-0 flex flex-col" keepMounted>
                            <NavTabBrowse />
                        </Tabs.Panel>
                        <Tabs.Panel value="chat" className="absolute inset-0 flex flex-col" keepMounted>
                            <Suspense
                                fallback={
                                    <div className="flex flex-col gap-px px-1 pt-2">
                                        {Array.from({ length: 15 }).map((_, index) => (
                                            <WrappingLoadingSkeleton fullWidth key={index}>
                                                <ButtonPrimitive aria-hidden inert menuItem />
                                            </WrappingLoadingSkeleton>
                                        ))}
                                    </div>
                                }
                            >
                                <NavTabChat />
                            </Suspense>
                        </Tabs.Panel>
                    </div>

                    <div className="border-b border-primary h-px" />

                    <div className="p-1">
                        <NavBarFooter isLayoutNavCollapsed={isLayoutNavCollapsed} />
                    </div>
                </Tabs.Root>
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

            {children}
        </div>
    )
}
