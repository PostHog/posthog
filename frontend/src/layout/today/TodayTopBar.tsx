import { TodayOrgMenu } from './TodayOrgMenu'
import { TodayProjectMenu } from './TodayProjectMenu'
import { TodayTopBarPanelTabs } from './TodayTopBarPanelTabs'
import { TodayTopBarQuickStartButton } from './TodayTopBarQuickStartButton'
import { TodayTopBarSearch } from './TodayTopBarSearch'

/**
 * The org menu takes the rail's width, so it sits right above the rail. The equal outer columns keep the search
 * centered on the whole bar.
 */
export function TodayTopBar(): JSX.Element {
    return (
        <header
            data-quill
            className="TodayTopBar grid grid-cols-[minmax(max-content,1fr)_minmax(10rem,36rem)_minmax(max-content,1fr)] items-center bg-[var(--chrome)]"
        >
            <div className="flex min-w-0 items-center">
                <div className="flex w-[var(--today-rail-width)] shrink-0 translate-y-1 justify-center">
                    <TodayOrgMenu />
                </div>
                <div className="flex min-w-0 items-center gap-0.5">
                    <TodayProjectMenu />
                    <TodayTopBarQuickStartButton />
                </div>
            </div>
            <div className="mx-2 min-w-0">
                <TodayTopBarSearch />
            </div>
            <div className="flex min-w-0 items-center justify-end pe-2">
                <TodayTopBarPanelTabs />
            </div>
        </header>
    )
}
