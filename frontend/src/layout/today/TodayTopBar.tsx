import { TodayOrgMenu } from './TodayOrgMenu'
import { TodayProjectMenu } from './TodayProjectMenu'
import { TodayTopBarPanelTabs } from './TodayTopBarPanelTabs'
import { TodayTopBarQuickStartButton } from './TodayTopBarQuickStartButton'
import { TodayTopBarSearch } from './TodayTopBarSearch'

/**
 * The first column is the rail's width, so the org menu sits right above the rail. The equal outer columns keep the
 * search centered.
 */
export function TodayTopBar(): JSX.Element {
    return (
        <header
            data-quill
            className="TodayTopBar grid grid-cols-[var(--today-rail-width)_minmax(max-content,1fr)_minmax(10rem,36rem)_minmax(max-content,1fr)] items-center bg-[var(--chrome)] pe-2"
        >
            <div className="flex translate-y-1 justify-center">
                <TodayOrgMenu />
            </div>
            <div className="flex min-w-0 items-center gap-0.5">
                <TodayProjectMenu />
                <TodayTopBarQuickStartButton />
            </div>
            <div className="mx-2 min-w-0">
                <TodayTopBarSearch />
            </div>
            <div className="flex min-w-0 items-center justify-end">
                <TodayTopBarPanelTabs />
            </div>
        </header>
    )
}
