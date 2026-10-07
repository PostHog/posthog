import './TodayShell.scss'

import { useActions, useMountedLogic, useValues } from 'kea'
import { Suspense, useEffect, useRef } from 'react'

import { Heading, Skeleton, ToastProvider } from '@posthog/quill'

import 'scenes/project-homepage/today/Today.scss'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useShortcut } from 'lib/components/Shortcuts/useShortcut'
import { cn } from 'lib/utils/css-classes'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { TodayHomeSidebar } from 'scenes/project-homepage/today/TodayHomeSidebar'

import { QuillSceneHeader } from '~/layout/scenes/components/QuillSceneHeader'

import { TodayPhoneHeader } from './TodayPhoneHeader'
import { TodayPreviewCardProvider } from './TodayPreviewCardProvider'
import { TodayRail } from './TodayRail'
import { todayRecentsLogic } from './todayRecentsLogic'
import { TODAY_RAIL_WIDTH, TODAY_SIDEBAR_CLOSE_THRESHOLD, clampSidebarWidth, todayShellLogic } from './todayShellLogic'
import { TodaySidebarFooter } from './TodaySidebarFooter'
import { TodayTabBar } from './TodayTabBar'
import { TodayWarehouseTabsPane } from './TodayWarehouseTabsPane'

const TodaySpacesPane = lazyWithRetry(() => import('./TodaySpacesPane').then((m) => ({ default: m.TodaySpacesPane })))
const TodayViewsSidebar = lazyWithRetry(() =>
    import('./TodayViewsSidebar').then((m) => ({ default: m.TodayViewsSidebar }))
)
const TodayProductsSidebar = lazyWithRetry(() =>
    import('./TodayProductsSidebar').then((m) => ({ default: m.TodayProductsSidebar }))
)
const NewSpaceDialog = lazyWithRetry(() =>
    import('products/tasks/frontend/spaces/NewSpaceDialog').then((m) => ({ default: m.NewSpaceDialog }))
)

const PANE_LABELS = {
    home: 'Today',
    spaces: 'Spaces',
    views: 'Views',
    products: 'Products',
    warehouse: 'Warehouse',
}

/** The left navigation under the Today layout: the rail, then the sidebar for the pane the rail has open. */
export function TodayShell({ className }: { className?: string }): JSX.Element {
    const { activePane, mobileLayout, phoneLayout, sidebarVisible, sidebarWidth, phoneHeaderHidden, sidebarInContent } =
        useValues(todayShellLogic)
    const { currentWarehouseItem } = useValues(todayShellLogic)
    const paneTitle =
        activePane === 'warehouse' ? (currentWarehouseItem?.label ?? PANE_LABELS.warehouse) : PANE_LABELS[activePane]
    // Records the tools and sessions visited while other panes are open, so each pane's Recent group is ready.
    useMountedLogic(todayRecentsLogic)
    const { setMobileSidebarOpen, setSidebarOpen, setSidebarWidth, toggleSidebar } = useActions(todayShellLogic)
    useShortcut({
        name: 'ToggleLeftNav',
        keybind: [keyBinds.toggleLeftNav, keyBinds.toggleLeftNavFallback],
        intent: 'Toggle collapse left navigation',
        interaction: 'function',
        callback: toggleSidebar,
        ignoreInEditable: true,
    })
    const sidebarRef = useRef<HTMLDivElement | null>(null)
    const drawerRef = useRef<HTMLElement | null>(null)
    const returnFocusRef = useRef<HTMLElement | null>(null)

    const resizerLogicProps: ResizerLogicProps = {
        // pinned: storage key for the persisted width. Renaming it resets everyone's sidebar width.
        logicKey: 'today-sidebar',
        placement: 'right',
        containerRef: sidebarRef,
        persistent: true,
        closeThreshold: TODAY_SIDEBAR_CLOSE_THRESHOLD,
        onToggleClosed: (closed) => setSidebarOpen(!closed),
        onDoubleClick: toggleSidebar,
    }
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    // The app layout reads the width from the shell logic to size the main column, so copy each change there.
    useEffect(() => {
        setSidebarWidth(clampSidebarWidth(desiredSize))
    }, [desiredSize, setSidebarWidth])

    useEffect(() => {
        if (!mobileLayout) {
            return
        }
        if (sidebarVisible) {
            returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
            drawerRef.current?.focus()
        } else if (returnFocusRef.current) {
            if (returnFocusRef.current.isConnected) {
                returnFocusRef.current.focus()
            }
            returnFocusRef.current = null
        }
    }, [mobileLayout, sidebarVisible])

    const paneContent = (
        <Suspense fallback={<Skeleton className="m-4 h-24" />}>
            {activePane === 'home' ? (
                <TodayPreviewCardProvider>
                    <TodayHomeSidebar />
                </TodayPreviewCardProvider>
            ) : activePane === 'spaces' ? (
                <TodaySpacesPane />
            ) : activePane === 'views' ? (
                <TodayViewsSidebar />
            ) : activePane === 'warehouse' ? (
                <TodayWarehouseTabsPane />
            ) : (
                <TodayProductsSidebar />
            )}
        </Suspense>
    )

    const pane = (
        <div className="TodayShell__pane">
            <QuillSceneHeader
                title={<h2 className="m-0 min-w-0 truncate text-base font-bold text-foreground">{paneTitle}</h2>}
            />
            {paneContent}
        </div>
    )

    const newSpaceDialog = activePane === 'spaces' && (
        <Suspense fallback={null}>
            <NewSpaceDialog />
        </Suspense>
    )

    if (phoneLayout) {
        return (
            <ToastProvider>
                <div data-quill className={cn('Today TodayShell TodayShell--phone', className)}>
                    {!sidebarVisible && !phoneHeaderHidden && <TodayPhoneHeader />}
                    <aside
                        ref={drawerRef}
                        tabIndex={-1}
                        className="TodayShell__sidebar TodayShell__page outline-none"
                        data-open={sidebarVisible}
                        aria-label={paneTitle}
                        aria-hidden={!sidebarVisible}
                        {...(sidebarVisible ? {} : { inert: '' })}
                    >
                        <div className="flex min-h-14 shrink-0 items-end gap-1 px-4 pt-3">
                            <Heading render={<h1 />} size="2xl" className="m-0 truncate leading-10">
                                {paneTitle}
                            </Heading>
                        </div>
                        <div className="TodayShell__pane">{paneContent}</div>
                        <TodaySidebarFooter />
                    </aside>
                    <TodayTabBar />
                    {newSpaceDialog}
                </div>
            </ToastProvider>
        )
    }

    return (
        <ToastProvider>
            <div
                data-quill
                className={cn('Today TodayShell bg-[var(--chrome)]', className)}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ '--today-rail-width': `${TODAY_RAIL_WIDTH}px` } as React.CSSProperties}
            >
                <TodayRail />
                {mobileLayout ? (
                    <>
                        <div
                            className="TodayShell__scrim"
                            data-open={sidebarVisible}
                            aria-hidden
                            onClick={() => setMobileSidebarOpen(false)}
                        />
                        <aside
                            ref={drawerRef}
                            tabIndex={-1}
                            className="TodayShell__sidebar TodayShell__drawer outline-none"
                            data-open={sidebarVisible}
                            aria-label={paneTitle}
                            aria-hidden={!sidebarVisible}
                            {...(sidebarVisible ? {} : { inert: '' })}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ width: sidebarWidth }}
                        >
                            {pane}
                            <TodaySidebarFooter />
                        </aside>
                    </>
                ) : (
                    sidebarVisible &&
                    !sidebarInContent && (
                        <aside
                            ref={sidebarRef}
                            className="TodayShell__sidebar relative border-r border-[var(--border)]"
                            aria-label={paneTitle}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ width: sidebarWidth }}
                        >
                            {pane}
                            <TodaySidebarFooter />
                            <Resizer {...resizerLogicProps} className="z-2" offset={0} />
                        </aside>
                    )
                )}
                {/* Mounted here so the sidebar and the spaces page open the same dialog. */}
                {newSpaceDialog}
            </div>
        </ToastProvider>
    )
}
