import { Tabs } from '@base-ui/react/tabs'
import { cva } from 'cva'
import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { Suspense, useEffect, useRef } from 'react'

import { IconApps, IconChat, IconChevronRight, IconFolderOpen, IconPlusSmall, IconTerminal } from '@posthog/icons'

import { NewAccountMenu } from 'lib/components/Account/NewAccountMenu'
import { commandLogic } from 'lib/components/Command/commandLogic'
import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useShortcut } from 'lib/components/Shortcuts/useShortcut'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Collapsible } from 'lib/ui/Collapsible/Collapsible'
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from 'lib/ui/DropdownMenu/DropdownMenu'
import { Label } from 'lib/ui/Label/Label'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'
import { isDesktopApp, isDesktopAppMac } from 'lib/utils/isDesktopApp'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { urls } from 'scenes/urls'

import {
    DESKTOP_PANEL_NAVBAR_DEFAULT_WIDTH,
    NavExperimentTab,
    PANEL_NAVBAR_COLLAPSE_THRESHOLD,
    PANEL_NAVBAR_DEFAULT_WIDTH,
    PanelLayoutNavIdentifier,
    panelLayoutLogic,
} from '~/layout/panel-layout/panelLayoutLogic'

import { NavSearchButton } from '../../../lib/components/NavSearchButton/NavSearchButton'
import { navigation3000Logic } from '../../navigation-3000/navigationLogic'
import { CreateMenu } from '../menus/CreateMenu'
import { NavBarFooter } from '../NavBarFooter'
import { PanelLayoutPanels } from './PanelLayoutPanels'
import { NavTabApps } from './tabs/NavTabApps'
import { NavTabBrowse } from './tabs/NavTabBrowse'
import { NavTabFiles } from './tabs/NavTabFiles'
const NavTabChat = lazyWithRetry(() => import('./tabs/NavTabChat').then((m) => ({ default: m.NavTabChat })))
const NavTabCode = lazyWithRetry(() => import('./tabs/NavTabCode').then((m) => ({ default: m.NavTabCode })))

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
                'flex items-center py-1 cursor-pointer group pl-2 sticky top-0 bg-surface-tertiary z-4 -mx-1 px-2 w-[calc(100%+(var(--spacing)*2))] -outline-offset-2',
                isCollapsed && 'mx-0 w-full px-px'
            )}
        >
            <Label
                intent="menu"
                className={cn(
                    'text-xxs text-secondary text-left group-hover:text-primary mr-1',
                    isCollapsed && 'text-[7px] m-0 w-full text-center'
                )}
            >
                {icon && !isCollapsed && <span className="size-3 mr-1">{icon}</span>}
                {label}
            </Label>
        </Collapsible.Trigger>
    )
}

export function PanelIndicatorIcon(): JSX.Element | null {
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)

    if (!isLayoutNavCollapsed) {
        return null
    }
    return (
        <span className="absolute bottom-3 -right-1.5 size-2">
            <IconChevronRight className="size-2 text-inherit" />
        </span>
    )
}

const WEB_TAB_CONFIG: { id: NavExperimentTab; label: string; icon: JSX.Element }[] = [
    { id: 'home', label: 'Browse', icon: <IconApps /> },
    { id: 'chat', label: 'Chat', icon: <IconChat className="text-ai" /> },
]

// The desktop app (products/desktop) restructures the sidepanel into Apps / Files / Chat / Code
const DESKTOP_TAB_CONFIG: { id: NavExperimentTab; label: string; icon: JSX.Element }[] = [
    { id: 'apps', label: 'Apps', icon: <IconApps /> },
    { id: 'files', label: 'Files', icon: <IconFolderOpen /> },
    { id: 'chat', label: 'Chat', icon: <IconChat className="text-ai" /> },
    { id: 'code', label: 'Code', icon: <IconTerminal /> },
]

// Keeps newDashboardLogic mounted while the Create button is visible, so the "Start from scratch"
// flow completes (and redirects) even after the menu closes and unmounts its own logic reference.
function CreateMenuLogics(): null {
    useMountedLogic(newDashboardLogic)
    return null
}

export function Nav(): JSX.Element {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const {
        toggleLayoutNavCollapsed,
        setNavExperimentTab,
        setActivePanelIdentifier,
        showLayoutPanel,
        clearActivePanelIdentifier,
        setNavbarWidth,
    } = useActions(panelLayoutLogic)
    const {
        isLayoutPanelVisible,
        isLayoutNavCollapsed,
        navExperimentActiveTab,
        activePanelIdentifier,
        visitedNavTabs,
    } = useValues(panelLayoutLogic)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { toggleCommand } = useActions(commandLogic)
    const showCreateButton = useFeatureFlag('CREATE_BUTTON_NAV_EXPERIMENT', 'test')

    const resizerLogicProps: ResizerLogicProps = {
        logicKey: 'panel-layout-navbar',
        placement: 'right',
        containerRef,
        persistent: true,
        closeThreshold: PANEL_NAVBAR_COLLAPSE_THRESHOLD,
        onToggleClosed: (shouldBeClosed) => toggleLayoutNavCollapsed(shouldBeClosed),
        onDoubleClick: () => toggleLayoutNavCollapsed(),
    }
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    // Grow to any width upward; never render narrower than the collapse snap so the live drag
    // stays in sync with where onToggleClosed flips to collapsed mode.
    const defaultNavbarWidth = isDesktopApp() ? DESKTOP_PANEL_NAVBAR_DEFAULT_WIDTH : PANEL_NAVBAR_DEFAULT_WIDTH
    const openWidth = Math.max(Math.round(desiredSize ?? defaultNavbarWidth), PANEL_NAVBAR_COLLAPSE_THRESHOLD)

    useEffect(() => {
        if (!isLayoutNavCollapsed && !isMobileLayout) {
            setNavbarWidth(openWidth)
        }
    }, [openWidth, isLayoutNavCollapsed, isMobileLayout, setNavbarWidth])

    // macOS desktop app: the title bar is hidden, so a full-width strip at the very top
    // reserves room for the traffic lights (and doubles as the window drag region)
    const trafficLightsSpace = isDesktopAppMac()

    const visibleTabs = isDesktopApp() ? DESKTOP_TAB_CONFIG : WEB_TAB_CONFIG
    // Persisted tab values from the other platform's tab set fall back to the first tab
    const activeTab = visibleTabs.some((tab) => tab.id === navExperimentActiveTab)
        ? navExperimentActiveTab
        : visibleTabs[0].id
    // Four tabs with icons + labels need ~300px; below that, drop the labels
    const iconOnlyTabs = visibleTabs.length === 4 && openWidth < 300

    useShortcut({
        name: 'ToggleLeftNav',
        keybind: [keyBinds.toggleLeftNav],
        intent: 'Toggle collapse left navigation',
        interaction: 'function',
        callback: toggleLayoutNavCollapsed,
    })

    function handlePanelTriggerClick(item: PanelLayoutNavIdentifier): void {
        if (activePanelIdentifier !== item) {
            setActivePanelIdentifier(item)
            showLayoutPanel(true)
        } else {
            clearActivePanelIdentifier()
            showLayoutPanel(false)
        }
    }

    // The search (and collapsed-mode chat) row. On the web it's the 40px navbar header at the
    // very top; in the desktop app it renders compact, below the Browse/Chat/Code tab strip.
    const headerRow = (
        <div
            className={cn(
                'flex justify-between items-center',
                isLayoutNavCollapsed
                    ? 'justify-center'
                    : !isDesktopApp()
                      ? 'h-[var(--scene-layout-header-height)]'
                      : undefined
            )}
        >
            <div
                className={cn('flex gap-1 rounded-md w-full px-2', isDesktopApp() ? 'py-1' : 'pt-2 pb-1', {
                    'flex-col items-center pt-2 pb-0': isLayoutNavCollapsed,
                })}
            >
                {/* Desktop app: the org/project switcher moves to the NavBarFooter (below
                    "More"), leaving only the traffic lights, tabs, and search up here */}
                {!isDesktopApp() && <NewAccountMenu isLayoutNavCollapsed={isLayoutNavCollapsed} />}

                <NavSearchButton isLayoutNavCollapsed={isLayoutNavCollapsed} toggleCommand={toggleCommand} />

                {isLayoutNavCollapsed && (
                    <ButtonPrimitive
                        className="group w-full justify-center"
                        data-attr="nav-tab-chat-collapsed"
                        iconOnly
                        tooltip="Chat"
                        tooltipPlacement="right"
                        active={activePanelIdentifier === 'Chat'}
                        onClick={() => {
                            const isOpening = activePanelIdentifier !== 'Chat'
                            posthog.capture('nav chat panel toggled', {
                                is_open: isOpening,
                            })
                            handlePanelTriggerClick('Chat')
                            if (isOpening) {
                                router.actions.push(urls.ai())
                            }
                        }}
                    >
                        <span
                            className={cn(
                                'relative flex size-4 text-secondary group-hover:text-primary opacity-50 group-hover:opacity-100 transition-all duration-50',
                                activePanelIdentifier === 'Chat' && 'text-primary opacity-100'
                            )}
                        >
                            <IconChat
                                className={cn(
                                    'text-secondary group-hover:text-ai',
                                    activePanelIdentifier === 'Chat' && 'text-primary'
                                )}
                            />

                            <PanelIndicatorIcon />
                        </span>
                    </ButtonPrimitive>
                )}
            </div>
        </div>
    )

    const createButton = showCreateButton ? (
        <div className={cn('px-2 py-1', isLayoutNavCollapsed && 'flex justify-center px-0')}>
            <CreateMenuLogics />
            <DropdownMenu
                onOpenChange={(open) => {
                    if (open) {
                        posthog.capture('nav create button clicked')
                    }
                }}
            >
                <DropdownMenuTrigger asChild>
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconPlusSmall />}
                        fullWidth={!isLayoutNavCollapsed}
                        center={!isLayoutNavCollapsed}
                        title={isLayoutNavCollapsed ? 'Create' : undefined}
                        data-attr="nav-create-button"
                    >
                        {!isLayoutNavCollapsed ? 'Create' : null}
                    </LemonButton>
                </DropdownMenuTrigger>
                <DropdownMenuContent side="bottom" align="start" className="min-w-[220px]">
                    <CreateMenu />
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    ) : null

    return (
        <div className="flex gap-0 relative">
            <nav
                className={cn(
                    navBarStyles({
                        isLayoutNavCollapsed,
                        isMobileLayout,
                    }),
                    isLayoutNavCollapsed && 'gap-px',
                    // Desktop app: product icons in the sidepanel keep their brand colors (the web
                    // app's flyout panels opt in per-panel via PanelLayoutPanel instead)
                    isDesktopApp() && 'group/colorful-product-icons colorful-product-icons-true'
                )}
                ref={containerRef}
            >
                {trafficLightsSpace && (
                    <div className="desktop-traffic-lights-spacer h-7 w-full shrink-0 flex items-center justify-end pr-1">
                        {/* Compact search in the title-bar strip, next to the traffic lights.
                            Collapsed mode keeps the icon button in the nav column instead. */}
                        {!isLayoutNavCollapsed && (
                            <ButtonPrimitive
                                size="xs"
                                onClick={() => toggleCommand()}
                                tooltip={
                                    <>
                                        Search <KeyboardShortcut command k />
                                    </>
                                }
                                tooltipPlacement="bottom"
                                className="relative top-1 h-5 px-1.5 text-xs text-secondary hover:text-primary"
                                data-attr="desktop-titlebar-search"
                            >
                                Search
                            </ButtonPrimitive>
                        )}
                    </div>
                )}
                {/* Web: search header at the very top. Desktop app: the Browse/Chat/Code tab
                    strip comes first (right below the traffic lights), then the search row —
                    both render inside Tabs.Root below. */}
                {!isDesktopApp() && (
                    <>
                        {headerRow}
                        {createButton}
                    </>
                )}

                <Tabs.Root
                    className="z-[var(--z-main-nav)] flex flex-col flex-1 overflow-hidden"
                    value={isLayoutNavCollapsed && activeTab !== 'home' ? 'home' : activeTab}
                    onValueChange={(value) => {
                        posthog.capture('nav tab clicked', { tab: value })
                        setNavExperimentTab(value as NavExperimentTab)
                        // In the desktop app, switching the sidepanel tab must not replace the
                        // current scene tab's content — the panels are self-sufficient
                        if (value === 'chat' && !isDesktopApp()) {
                            router.actions.push(urls.ai())
                        }
                    }}
                    orientation={isLayoutNavCollapsed ? 'vertical' : 'horizontal'}
                >
                    <div className={cn('p-1', isLayoutNavCollapsed && 'hidden')}>
                        <Tabs.List className="relative flex items-center gap-1 shrink-0 z-0 p-1 rounded-lg bg-(--color-bg-fill-highlight-50) dark:bg-surface-primary">
                            {visibleTabs.map((tab) => (
                                <Tabs.Tab
                                    key={tab.id}
                                    value={tab.id}
                                    render={(props) => (
                                        <ButtonPrimitive
                                            {...props}
                                            className={cn(
                                                'group data-[composite-item-active]:bg-surface-tertiary justify-center',
                                                visibleTabs.length === 4
                                                    ? 'w-1/4'
                                                    : visibleTabs.length === 3
                                                      ? 'w-1/3'
                                                      : 'w-1/2'
                                            )}
                                            data-attr={`nav-tab-${tab.id}`}
                                            tooltip={iconOnlyTabs ? tab.label : undefined}
                                            tooltipPlacement="bottom"
                                        >
                                            <span
                                                className={cn(
                                                    'flex size-4',
                                                    activeTab === tab.id
                                                        ? 'text-primary'
                                                        : 'text-secondary group-hover:text-primary'
                                                )}
                                            >
                                                {tab.icon}
                                            </span>
                                            {!iconOnlyTabs && (
                                                <span
                                                    className={cn(
                                                        'text-xs',
                                                        activeTab === tab.id
                                                            ? 'text-primary'
                                                            : 'text-secondary group-hover:text-primary'
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
                    </div>

                    {isDesktopApp() && (
                        <>
                            {/* Expanded desktop nav gets its search from the title-bar strip up
                                top; the header row only remains for the collapsed icon column */}
                            {isLayoutNavCollapsed && headerRow}
                            {createButton}
                        </>
                    )}

                    <div className="flex-1 overflow-hidden relative">
                        <Tabs.Panel value="home" className="absolute inset-0 flex flex-col" keepMounted tabIndex={-1}>
                            <NavTabBrowse />
                        </Tabs.Panel>
                        {isDesktopApp() && (
                            <Tabs.Panel
                                value="apps"
                                className="absolute inset-0 flex flex-col"
                                keepMounted
                                tabIndex={-1}
                            >
                                <NavTabApps />
                            </Tabs.Panel>
                        )}
                        {isDesktopApp() && visitedNavTabs.includes('files') && (
                            <Tabs.Panel
                                value="files"
                                className="absolute inset-0 flex flex-col"
                                keepMounted
                                tabIndex={-1}
                            >
                                <NavTabFiles />
                            </Tabs.Panel>
                        )}
                        {/* Lazy until first activated: the visited list only ever grows, so once
                            mounted the panel never unmounts — keepMounted then preserves it across
                            tab switches. Users who never open chat never pay for its chunk. */}
                        {visitedNavTabs.includes('chat') && (
                            <Tabs.Panel
                                value="chat"
                                className="absolute inset-0 flex flex-col"
                                keepMounted
                                tabIndex={-1}
                            >
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
                        )}
                        {/* Same lazy pattern as chat: mounted on first visit, kept mounted after */}
                        {isDesktopApp() && visitedNavTabs.includes('code') && (
                            <Tabs.Panel
                                value="code"
                                className="absolute inset-0 flex flex-col"
                                keepMounted
                                tabIndex={-1}
                            >
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
                                    <NavTabCode />
                                </Suspense>
                            </Tabs.Panel>
                        )}
                    </div>

                    <div className="px-2">
                        <div className="h-px bg-border-primary " />
                    </div>

                    <div className="p-1">
                        <NavBarFooter isLayoutNavCollapsed={isLayoutNavCollapsed} />
                    </div>
                </Tabs.Root>
                {!isMobileLayout && (
                    <Resizer
                        {...resizerLogicProps}
                        data-attr="tree-navbar-resizer"
                        className={cn('top-3 -right-px bottom-4 z-2', {
                            'top-0': isLayoutPanelVisible,
                        })}
                        offset={0}
                    />
                )}
            </nav>

            {/* Desktop renders panel content inline next to the nav (PanelLayoutPanel's
                ResizableElement positions it via left:100% of this flex parent). On mobile we
                lift the panel out to PanelLayout.tsx so it can have its own stacking context
                independent of #project-panel-layout — this lets the dim overlay slot between
                the nav and the panel. */}
            {!isMobileLayout && <PanelLayoutPanels />}
        </div>
    )
}
