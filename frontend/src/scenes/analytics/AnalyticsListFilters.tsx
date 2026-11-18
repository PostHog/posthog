import { useActions, useValues } from 'kea'

import { AnalyticsFilterMenu } from './AnalyticsFilterMenu'
import { analyticsListLogic } from './analyticsListLogic'
import { AnalyticsSearchInput } from './AnalyticsSearchInput'

/** Search, and beside it the one menu of the list's controls. */
export function AnalyticsListFilters(): JSX.Element {
    const { searchInput } = useValues(analyticsListLogic)
    const { setSearchInput } = useActions(analyticsListLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <AnalyticsSearchInput
                value={searchInput}
                onChange={setSearchInput}
                label="Search analytics"
                placeholder="Search"
                dataAttr="analytics-list-search"
            />
            <AnalyticsFilterMenu />
        </div>
    )
}
