import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { cn } from 'lib/utils/css-classes'
import { TodayHomeSidebar } from 'scenes/project-homepage/today/TodayHomeSidebar'

import { TodayLibrarySidebar } from './TodayLibrarySidebar'
import { TodayQuillRoot } from './TodayQuillRoot'
import { TodayRail } from './TodayRail'
import { TODAY_SIDEBAR_CLOSE_THRESHOLD, clampSidebarWidth, todayShellLogic } from './todayShellLogic'
import { TodaySidebarFooter } from './TodaySidebarFooter'
import { TodaySpacesSidebar } from './TodaySpacesSidebar'
import { TodayToolsSidebar } from './TodayToolsSidebar'

const PANE_LABELS = { home: 'Today', spaces: 'Spaces', library: 'Library', tools: 'Tools' }

/** The left navigation under the Today layout: the rail, then the sidebar for the pane the rail has open. */
export function TodayShell({ className }: { className?: string }): JSX.Element {
    const { activePane, sidebarOpen, sidebarWidth } = useValues(todayShellLogic)
    const { setSidebarOpen, setSidebarWidth, toggleSidebar } = useActions(todayShellLogic)
    const sidebarRef = useRef<HTMLDivElement | null>(null)

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

    return (
        <TodayQuillRoot className={cn('flex h-full min-h-0 overflow-hidden', className)}>
            <TodayRail />
            {sidebarOpen && (
                <aside
                    ref={sidebarRef}
                    className="relative flex h-full min-w-0 flex-col"
                    aria-label={PANE_LABELS[activePane]}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: sidebarWidth }}
                >
                    <div className="min-h-0 flex-1">
                        {activePane === 'home' ? (
                            <TodayHomeSidebar />
                        ) : activePane === 'spaces' ? (
                            <TodaySpacesSidebar />
                        ) : activePane === 'library' ? (
                            <TodayLibrarySidebar />
                        ) : (
                            <TodayToolsSidebar />
                        )}
                    </div>
                    <TodaySidebarFooter />
                    <Resizer {...resizerLogicProps} className="z-2" offset={0} />
                </aside>
            )}
        </TodayQuillRoot>
    )
}
