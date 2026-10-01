import './TodayShell.scss'

import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { ToastProvider } from '@posthog/quill'

import 'scenes/project-homepage/today/Today.scss'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { cn } from 'lib/utils/css-classes'
import { TodayHomeSidebar } from 'scenes/project-homepage/today/TodayHomeSidebar'

import { NewSpaceDialog } from 'products/tasks/frontend/spaces/NewSpaceDialog'

import { TodayLibrarySidebar } from './TodayLibrarySidebar'
import { TodayPreviewCardProvider } from './TodayPreviewCardProvider'
import { TodayRail } from './TodayRail'
import { TODAY_RAIL_WIDTH, TODAY_SIDEBAR_CLOSE_THRESHOLD, clampSidebarWidth, todayShellLogic } from './todayShellLogic'
import { TodaySidebarFooter } from './TodaySidebarFooter'
import { TodaySpacesSidebar } from './TodaySpacesSidebar'
import { TodayToolsSidebar } from './TodayToolsSidebar'

const PANE_LABELS = { home: 'Today', spaces: 'Spaces', library: 'Library', tools: 'Tools' }

/** The left navigation under the Today layout: the rail, then the sidebar for the pane the rail has open. */
export function TodayShell({ className }: { className?: string }): JSX.Element {
    const { activePane, mobileLayout, sidebarVisible, sidebarWidth } = useValues(todayShellLogic)
    const { setMobileSidebarOpen, setSidebarOpen, setSidebarWidth, toggleSidebar } = useActions(todayShellLogic)
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

    const pane = (
        <div className="TodayShell__pane">
            {activePane === 'home' ? (
                <TodayHomeSidebar />
            ) : activePane === 'spaces' ? (
                <TodayPreviewCardProvider>
                    <TodaySpacesSidebar />
                </TodayPreviewCardProvider>
            ) : activePane === 'library' ? (
                <TodayLibrarySidebar />
            ) : (
                <TodayToolsSidebar />
            )}
        </div>
    )

    return (
        <ToastProvider>
            <div
                className={cn('Today TodayShell', className)}
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
                            className="TodayShell__sidebar relative"
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
                <NewSpaceDialog />
            </div>
        </ToastProvider>
    )
}
