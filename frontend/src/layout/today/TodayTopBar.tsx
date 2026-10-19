import { TodayProjectMenu } from './TodayProjectMenu'
import { TodayTopBarPanelTabs } from './TodayTopBarPanelTabs'
import { TodayTopBarQuickStartButton } from './TodayTopBarQuickStartButton'
import { TodayTopBarSearch } from './TodayTopBarSearch'

/** The equal outer columns keep the search centered. */
export function TodayTopBar(): JSX.Element {
    return (
        <header
            data-quill
            className="TodayTopBar grid grid-cols-[minmax(max-content,1fr)_minmax(10rem,36rem)_minmax(max-content,1fr)] items-center gap-2 bg-[var(--chrome)] pe-2"
        >
            <div className="flex min-w-0 items-center gap-0.5">
                <TodayProjectMenu />
            </div>
            <TodayTopBarSearch />
            <div className="flex min-w-0 items-center gap-2">
                <TodayTopBarQuickStartButton />
                <div className="ms-auto">
                    <TodayTopBarPanelTabs />
                </div>
            </div>
        </header>
    )
}
