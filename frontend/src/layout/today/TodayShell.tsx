import './TodayShell.scss'

import { useActions, useValues } from 'kea'
import { Suspense, useEffect, useRef } from 'react'

import { Skeleton, ToastProvider } from '@posthog/quill'

import 'scenes/project-homepage/today/Today.scss'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useShortcut } from 'lib/components/Shortcuts/useShortcut'
import { cn } from 'lib/utils/css-classes'
import { lazyWithRetry } from 'lib/utils/retryImport'

import { QuillSceneHeader } from '~/layout/scenes/components/QuillSceneHeader'

import { TodayPhoneHeader } from './TodayPhoneHeader'
import { TodayRail } from './TodayRail'
import { TODAY_PANES } from './todayRailItems'
import { TODAY_RAIL_WIDTH, TODAY_SIDEBAR_CLOSE_THRESHOLD, clampSidebarWidth, todayShellLogic } from './todayShellLogic'
import { TodaySidebarCollapseButton } from './TodaySidebarCollapseButton'
import { TodaySidebarFooter } from './TodaySidebarFooter'
import { TodaySidebarPinButton } from './TodaySidebarPinButton'
import { TodayTabBar } from './TodayTabBar'

const TodaySpacesPane = lazyWithRetry(() => import('./TodaySpacesPane').then((m) => ({ default: m.TodaySpacesPane })))
const TodayAnalyticsSidebar = lazyWithRetry(() =>
    import('./TodayAnalyticsSidebar').then((m) => ({ default: m.TodayAnalyticsSidebar }))
)
const TodayProductsPane = lazyWithRetry(() =>
    import('./TodayProductsPane').then((m) => ({ default: m.TodayProductsPane }))
)
const TodaySettingsSidebar = lazyWithRetry(() =>
    import('./TodaySettingsSidebar').then((m) => ({ default: m.TodaySettingsSidebar }))
)
const NewSpaceDialog = lazyWithRetry(() =>
    import('products/tasks/frontend/spaces/NewSpaceDialog').then((m) => ({ default: m.NewSpaceDialog }))
)

/** The left navigation under the Today layout: the rail, then the sidebar for the pane the rail has open. */
export function TodayShell({ className }: { className?: string }): JSX.Element {
    const { activePane, mobileLayout, phoneLayout, sidebarVisible, sidebarWidth, phoneHeaderHidden } =
        useValues(todayShellLogic)
    const { setMobileSidebarOpen, setSidebarOpen, setSidebarWidth, toggleSidebar } = useActions(todayShellLogic)
    useShortcut({
        name: 'ToggleLeftNav',
        keybind: [keyBinds.toggleLeftNav, keyBinds.toggleLeftNavFallback],
        intent: 'Toggle collapse left navigation',
        interaction: 'function',
        callback: () => toggleSidebar('shortcut'),
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
        onDoubleClick: () => toggleSidebar('resizer'),
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
            {activePane === 'home' ? null : activePane === 'spaces' ? (
                <TodaySpacesPane />
            ) : activePane === 'analytics' ? (
                <TodayAnalyticsSidebar />
            ) : activePane === 'settings' ? (
                <TodaySettingsSidebar />
            ) : (
                <TodayProductsPane />
            )}
        </Suspense>
    )

    const { title: paneTitle, action: PaneAction } = TODAY_PANES[activePane]
    const pane = (
        <div className="TodayShell__pane">
            <QuillSceneHeader
                // Transparent, not removed: the scene header keeps its border inside the same height, so both headers
                // center their buttons on the same line.
                className="group/header border-b-transparent"
                back={<TodaySidebarCollapseButton />}
                title={
                    <div className="flex min-w-0 items-center gap-1">
                        <h2 className="m-0 min-w-0 truncate text-base font-bold text-foreground">{paneTitle}</h2>
                        <TodaySidebarPinButton />
                    </div>
                }
                actions={PaneAction && <PaneAction />}
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
                        className="group/sidebar TodayShell__sidebar TodayShell__page outline-none"
                        data-open={sidebarVisible}
                        aria-label={paneTitle}
                        aria-hidden={!sidebarVisible}
                        {...(sidebarVisible ? {} : { inert: '' })}
                    >
                        {pane}
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
                            className="group/sidebar TodayShell__sidebar TodayShell__drawer outline-none"
                            data-open={sidebarVisible}
                            aria-label={paneTitle}
                            aria-hidden={!sidebarVisible}
                            {...(sidebarVisible ? {} : { inert: '' })}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ width: sidebarWidth }}
                        >
                            {pane}
                        </aside>
                    </>
                ) : (
                    sidebarVisible && (
                        <aside
                            ref={sidebarRef}
                            className="group/sidebar TodayShell__sidebar TodayShell__sidebar--framed relative bg-surface-primary"
                            aria-label={paneTitle}
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ width: sidebarWidth }}
                        >
                            {pane}
                            {/* The frame already draws the seam, so the handle's own line shows only on hover. */}
                            <Resizer {...resizerLogicProps} visible={false} className="z-2" offset={0} />
                        </aside>
                    )
                )}
                {/* Mounted here so the sidebar and the spaces page open the same dialog. */}
                {newSpaceDialog}
            </div>
        </ToastProvider>
    )
}
