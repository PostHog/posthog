import './NavBar.scss'

import { Tabs } from '@base-ui/react/tabs'
import { cva } from 'cva'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { Suspense, useEffect, useRef } from 'react'

import { IconApps, IconChat, IconChevronRight, IconFolderOpen } from '@posthog/icons'

import { NewAccountMenu } from 'lib/components/Account/NewAccountMenu'
import { commandLogic } from 'lib/components/Command/commandLogic'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useShortcut } from 'lib/components/Shortcuts/useShortcut'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Collapsible } from 'lib/ui/Collapsible/Collapsible'
import { Label } from 'lib/ui/Label/Label'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { urls } from 'scenes/urls'

import {
    NavExperimentTab,
    PANEL_NAVBAR_COLLAPSE_THRESHOLD,
    PANEL_NAVBAR_DEFAULT_WIDTH,
    PanelLayoutNavIdentifier,
    panelLayoutLogic,
} from '~/layout/panel-layout/panelLayoutLogic'
import { uiCustomizationLogic } from '~/layout/uiCustomizationLogic'

import { NavSearchBar, NavSearchButton } from '../../../lib/components/NavSearchButton/NavSearchButton'
import { navigation3000Logic } from '../../navigation-3000/navigationLogic'
import { NavBarFooter } from './NavBarFooter'
import { PanelLayoutPanels } from './PanelLayoutPanels'
import { FlatNavBrowse } from './tabs/flat-nav/FlatNavBrowse'
import { NavTabApps } from './tabs/NavTabApps'
import { NavTabBrowse } from './tabs/NavTabBrowse'
import { NavTabFiles } from './tabs/NavTabFiles'
const NavTabChat = lazyWithRetry(() => import('./tabs/NavTabChat').then((m) => ({ default: m.NavTabChat })))

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
                'flex items-center py-[var(--nav-section-trigger-padding-y,0.25rem)] cursor-pointer group pl-2 sticky top-0 bg-surface-tertiary z-4 -mx-1 px-2 w-[calc(100%+(var(--spacing)*2))] -outline-offset-2',
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

// The Apps tab keeps the persisted tab ID and analytics identifiers used by Browse.
const SIMPLE_TAB_CONFIG: { id: NavExperimentTab; label: string; icon: JSX.Element }[] = [
    { id: 'home', label: 'Apps', icon: <IconApps /> },
    { id: 'files', label: 'Files', icon: <IconFolderOpen /> },
    { id: 'chat', label: 'Chat', icon: <IconChat className="text-ai" /> },
]

const TAB_CONFIG: { id: NavExperimentTab; label: string; icon: JSX.Element }[] = [
    { id: 'home', label: 'Browse', icon: <IconApps /> },
    { id: 'chat', label: 'Chat', icon: <IconChat className="text-ai" /> },
]

export function NavBar(): JSX.Element {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const {
        toggleLayoutNavCollapsed,
        setNavExperimentTab,
        setActivePanelIdentifier,
        showLayoutPanel,
        clearActivePanelIdentifier,
        setNavbarWidth,
        setNavOverlayOpen,
    } = useActions(panelLayoutLogic)
    const {
        isLayoutPanelVisible,
        isLayoutNavCollapsed: isNavCollapsed,
        isNavOverlayOpen,
        navExperimentActiveTab,
        activePanelIdentifier,
        visitedNavTabs,
    } = useValues(panelLayoutLogic)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { toggleCommand } = useActions(commandLogic)
    const { sidebarDensity } = useValues(uiCustomizationLogic)
    const isSimpleSidepanelEnabled = useFeatureFlag('SIMPLE_SIDEPANEL')
    const isOverlayOpen = isSimpleSidepanelEnabled && isNavCollapsed && isNavOverlayOpen
    const isLayoutNavCollapsed = isNavCollapsed && !isOverlayOpen
    const isFlatNavEnabled = useFeatureFlag('FLAT_NAV', 'test')
    const activeTab =
        !isSimpleSidepanelEnabled &&
        (navExperimentActiveTab === 'files' || (isLayoutNavCollapsed && navExperimentActiveTab === 'chat'))
            ? 'home'
            : navExperimentActiveTab

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
    const openWidth = Math.max(Math.round(desiredSize ?? PANEL_NAVBAR_DEFAULT_WIDTH), PANEL_NAVBAR_COLLAPSE_THRESHOLD)

    useEffect(() => {
        if (!isNavCollapsed && !isMobileLayout) {
            setNavbarWidth(openWidth)
        }
    }, [openWidth, isNavCollapsed, isMobileLayout, setNavbarWidth])

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

    function openCollapsedTab(tab: NavExperimentTab): void {
        if (isSimpleSidepanelEnabled && isNavCollapsed) {
            if (tab === 'chat') {
                toggleLayoutNavCollapsed(false)
            } else {
                setNavOverlayOpen(true)
            }
        }
    }

    return (
        <div className={cn('flex gap-0 relative', isOverlayOpen && 'w-[var(--project-navbar-width-collapsed)]')}>
            {isOverlayOpen && (
                <button
                    type="button"
                    className="fixed inset-0 z-[var(--z-layout-navbar)] cursor-default"
                    aria-label="Close navigation"
                    data-attr="nav-overlay-dismiss"
                    tabIndex={-1}
                    onClick={() => setNavOverlayOpen(false)}
                />
            )}
            <nav
                className={cn(
                    navBarStyles({
                        isLayoutNavCollapsed,
                        isMobileLayout,
                    }),
                    isLayoutNavCollapsed && 'gap-px',
                    isSimpleSidepanelEnabled && '@container/sidebar',
                    isOverlayOpen && 'absolute top-0 left-0 shadow-lg border-r'
                )}
                data-nav-density={sidebarDensity}
                data-nav-overlay={isOverlayOpen || undefined}
                onKeyDown={(event) => {
                    if (isOverlayOpen && event.key === 'Escape' && !event.defaultPrevented) {
                        event.stopPropagation()
                        setNavOverlayOpen(false)
                        containerRef.current?.querySelector<HTMLElement>('[role="tab"][aria-selected="true"]')?.focus()
                    }
                }}
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
                            'items-center': isSimpleSidepanelEnabled,
                            'flex-col items-center pt-2 pb-0': isLayoutNavCollapsed,
                        })}
                    >
                        <NewAccountMenu isLayoutNavCollapsed={isLayoutNavCollapsed} />

                        {isSimpleSidepanelEnabled ? (
                            <NavSearchButton toggleCommand={toggleCommand} showShortcut={!isLayoutNavCollapsed} />
                        ) : (
                            <>
                                {/* Collapsed nav has no room for the search bar, so it keeps the icon-only trigger */}
                                {isLayoutNavCollapsed && <NavSearchButton toggleCommand={toggleCommand} />}

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
                            </>
                        )}
                    </div>
                </div>

                {!isSimpleSidepanelEnabled && !isLayoutNavCollapsed && (
                    <div className="px-2 py-1">
                        <NavSearchBar toggleCommand={toggleCommand} />
                    </div>
                )}

                <Tabs.Root
                    className="z-[var(--z-main-nav)] flex flex-col flex-1 overflow-hidden"
                    value={activeTab}
                    onValueChange={(value) => {
                        posthog.capture('nav tab clicked', { tab: value })
                        setNavExperimentTab(value as NavExperimentTab)
                        openCollapsedTab(value as NavExperimentTab)
                        if (isSimpleSidepanelEnabled) {
                            clearActivePanelIdentifier()
                            showLayoutPanel(false)
                        }
                        if (value === 'chat') {
                            router.actions.push(urls.ai())
                        }
                    }}
                    orientation={isLayoutNavCollapsed ? 'vertical' : 'horizontal'}
                >
                    <div className={cn('p-1', !isSimpleSidepanelEnabled && isLayoutNavCollapsed && 'hidden')}>
                        <Tabs.List
                            className={cn(
                                'relative flex items-center gap-1 shrink-0 z-0 p-1 rounded-lg bg-(--color-bg-fill-highlight-50) dark:bg-surface-primary',
                                isSimpleSidepanelEnabled && isLayoutNavCollapsed && 'flex-col'
                            )}
                        >
                            {(isSimpleSidepanelEnabled ? SIMPLE_TAB_CONFIG : TAB_CONFIG).map((tab) => (
                                <Tabs.Tab
                                    key={tab.id}
                                    value={tab.id}
                                    onClick={() => openCollapsedTab(tab.id)}
                                    render={(props) => (
                                        <ButtonPrimitive
                                            {...props}
                                            className={cn(
                                                'group data-[composite-item-active]:bg-surface-tertiary justify-center',
                                                isSimpleSidepanelEnabled ? 'flex-1 min-w-0' : 'w-1/2'
                                            )}
                                            iconOnly={isSimpleSidepanelEnabled && isLayoutNavCollapsed}
                                            tooltip={isSimpleSidepanelEnabled ? tab.label : undefined}
                                            aria-label={tab.label}
                                            data-attr={
                                                isSimpleSidepanelEnabled && isLayoutNavCollapsed && tab.id === 'chat'
                                                    ? 'nav-tab-chat-collapsed'
                                                    : `nav-tab-${tab.id}`
                                            }
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
                                            {!isLayoutNavCollapsed && (
                                                <span
                                                    className={cn(
                                                        'text-xs',
                                                        isSimpleSidepanelEnabled && '@max-[200px]/sidebar:hidden',
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

                    <div
                        className={cn(
                            'flex-1 overflow-hidden relative',
                            isSimpleSidepanelEnabled && isLayoutNavCollapsed && '[&>*]:hidden'
                        )}
                    >
                        <Tabs.Panel value="home" className="absolute inset-0 flex flex-col" keepMounted tabIndex={-1}>
                            {isSimpleSidepanelEnabled ? (
                                <NavTabApps />
                            ) : isFlatNavEnabled ? (
                                <FlatNavBrowse />
                            ) : (
                                <NavTabBrowse />
                            )}
                        </Tabs.Panel>
                        {isSimpleSidepanelEnabled && visitedNavTabs.includes('files') && (
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
                    </div>

                    <div className="px-2">
                        <div className="h-px bg-border-primary " />
                    </div>

                    <div className={cn('p-1', !isSimpleSidepanelEnabled && isLayoutNavCollapsed && 'hidden')}>
                        <NavBarFooter isLayoutNavCollapsed={isLayoutNavCollapsed} />
                    </div>
                </Tabs.Root>
                {!isMobileLayout && !isOverlayOpen && (
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
