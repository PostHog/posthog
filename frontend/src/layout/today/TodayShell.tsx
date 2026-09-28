import './TodayShell.scss'

import { useValues } from 'kea'

import 'scenes/project-homepage/today/Today.scss'
import { cn } from 'lib/utils/css-classes'
import { TodayHomeSidebar } from 'scenes/project-homepage/today/TodayHomeSidebar'

import { TodayLibrarySidebar } from './TodayLibrarySidebar'
import { TodayRail } from './TodayRail'
import { todayShellLogic, TODAY_SIDEBAR_WIDTH } from './todayShellLogic'
import { TodaySidebarFooter } from './TodaySidebarFooter'
import { TodaySpacesSidebar } from './TodaySpacesSidebar'
import { TodayToolsSidebar } from './TodayToolsSidebar'

const PANE_LABELS = { home: 'Today', spaces: 'Spaces', library: 'Library', tools: 'Tools' }

/** The left navigation under the Today layout: the rail, then the sidebar for the pane the rail has open. */
export function TodayShell({ className }: { className?: string }): JSX.Element {
    const { activePane, sidebarOpen } = useValues(todayShellLogic)

    return (
        <div className={cn('Today TodayShell', className)}>
            <TodayRail />
            {sidebarOpen && (
                <aside
                    className="TodayShell__sidebar"
                    aria-label={PANE_LABELS[activePane]}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: TODAY_SIDEBAR_WIDTH }}
                >
                    <div className="TodayShell__pane">
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
                </aside>
            )}
        </div>
    )
}
