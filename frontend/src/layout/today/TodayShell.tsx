import './TodayShell.scss'

import { useActions, useMountedLogic, useValues } from 'kea'
import { Suspense, useEffect, useRef } from 'react'

import { IconChevronLeft } from '@posthog/icons'
import { Button, Heading, Skeleton, ToastProvider } from '@posthog/quill'

import 'scenes/project-homepage/today/Today.scss'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { cn } from 'lib/utils/css-classes'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { TodayHomeSidebar } from 'scenes/project-homepage/today/TodayHomeSidebar'

import { QuillSceneHeader } from '~/layout/scenes/components/QuillSceneHeader'

import { TodayPhoneHeader } from './TodayPhoneHeader'
import { TodayPreviewCardProvider } from './TodayPreviewCardProvider'
import { TodayRail } from './TodayRail'
import { todayRecentsLogic } from './todayRecentsLogic'
import {
    TODAY_MORE_PANES,
    TODAY_RAIL_WIDTH,
    TODAY_SIDEBAR_CLOSE_THRESHOLD,
    clampSidebarWidth,
    todayShellLogic,
} from './todayShellLogic'
import { TodaySidebarFooter } from './TodaySidebarFooter'
import { TodayTabBar } from './TodayTabBar'

const TodaySpacesPane = lazyWithRetry(() => import('./TodaySpacesPane').then((m) => ({ default: m.TodaySpacesPane })))
const TodayAnalyticsSidebar = lazyWithRetry(() =>
    import('./TodayAnalyticsSidebar').then((m) => ({ default: m.TodayAnalyticsSidebar }))
)
const TodayToolsSidebar = lazyWithRetry(() =>
    import('./TodayToolsSidebar').then((m) => ({ default: m.TodayToolsSidebar }))
)
const TodayMoreSidebar = lazyWithRetry(() =>
    import('./TodayMoreSidebar').then((m) => ({ default: m.TodayMoreSidebar }))
)
const TodayLibrarySidebar = lazyWithRetry(() =>
    import('./TodayLibrarySidebar').then((m) => ({ default: m.TodayLibrarySidebar }))
)
const NewSpaceDialog = lazyWithRetry(() =>
    import('products/tasks/frontend/spaces/NewSpaceDialog').then((m) => ({ default: m.NewSpaceDialog }))
)

const PANE_LABELS = {
    home: 'Today',
    spaces: 'Spaces',
    analytics: 'Analytics',
    library: 'Library',
    tools: 'Tools',
    more: 'More',
}

/** The left navigation under the Today layout: the rail, then the sidebar for the pane the rail has open. */
export function TodayShell({ className }: { className?: string }): JSX.Element {
    const { activePane, mobileLayout, phoneLayout, sidebarVisible, sidebarWidth, phoneHeaderHidden } =
        useValues(todayShellLogic)
    // Records the tools and sessions visited while other panes are open, so each pane's Recent group is ready.
    useMountedLogic(todayRecentsLogic)
    const { pickPane, setMobileSidebarOpen, setSidebarOpen, setSidebarWidth, toggleSidebar } =
        useActions(todayShellLogic)
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
            ) : activePane === 'analytics' ? (
                <TodayAnalyticsSidebar />
            ) : activePane === 'library' ? (
                <TodayLibrarySidebar />
            ) : activePane === 'more' ? (
                <TodayMoreSidebar />
            ) : (
                <TodayToolsSidebar />
            )}
        </Suspense>
    )

    const pane = (
        <div className="TodayShell__pane">
            <QuillSceneHeader
                title={
                    <h2 className="m-0 min-w-0 truncate text-base font-bold text-foreground">
                        {PANE_LABELS[activePane]}
                    </h2>
                }
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
                        aria-label={PANE_LABELS[activePane]}
                        aria-hidden={!sidebarVisible}
                        {...(sidebarVisible ? {} : { inert: '' })}
                    >
                        <div className="flex min-h-14 shrink-0 items-end gap-1 px-4 pt-3">
                            {TODAY_MORE_PANES.includes(activePane) && (
                                <Button
                                    size="icon-lg"
                                    className="-ml-2"
                                    aria-label="Back to More"
                                    data-attr="today-more-back"
                                    onClick={() => pickPane('more')}
                                >
                                    <IconChevronLeft />
                                </Button>
                            )}
                            <Heading render={<h1 />} size="2xl" className="m-0 truncate leading-10">
                                {PANE_LABELS[activePane]}
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
                            aria-label={PANE_LABELS[activePane]}
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
                    sidebarVisible && (
                        <aside
                            ref={sidebarRef}
                            className="TodayShell__sidebar relative border-r border-[var(--border)]"
                            aria-label={PANE_LABELS[activePane]}
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
