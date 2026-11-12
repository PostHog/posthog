import { useActions, useValues } from 'kea'

import { AnalyticsColumnPicker } from './AnalyticsColumnPicker'
import { AnalyticsFilterMenu } from './AnalyticsFilterMenu'
import { analyticsListLogic } from './analyticsListLogic'
import { AnalyticsSearchInput } from './AnalyticsSearchInput'

/** Search and the menu of the list's filters, with the column picker across from them. A folder keeps its own columns. */
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
                    <AnalyticsColumnPicker />
                </div>
            )}
        </div>
    )
}
