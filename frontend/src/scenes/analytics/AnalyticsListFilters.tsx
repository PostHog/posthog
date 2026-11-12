import { useActions, useValues } from 'kea'

import { AnalyticsFilterMenu } from './AnalyticsFilterMenu'
import { analyticsListLogic } from './analyticsListLogic'
import { AnalyticsSearchInput } from './AnalyticsSearchInput'
import { AnalyticsSortSelect } from './AnalyticsSortSelect'

/** Search and the menu of the list's filters, with the order across from them. A folder lists by name, so it has no order. */
export function AnalyticsListFilters(): JSX.Element {
    const { searchInput, mode } = useValues(analyticsListLogic)
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
            {mode === 'feed' && (
                <div className="ml-auto">
                    <AnalyticsSortSelect />
                </div>
            )}
        </div>
    )
}
