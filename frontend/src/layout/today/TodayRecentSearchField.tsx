import { useActions, useValues } from 'kea'

import { TodayPaneSearchField } from './TodayPaneSearchField'
import { todaySpacesLogic } from './todaySpacesLogic'

export function TodayRecentSearchField(): JSX.Element {
    const { recentQuery, recentItems } = useValues(todaySpacesLogic)
    const { setRecentQuery, setRecentSearchOpen } = useActions(todaySpacesLogic)

    return (
        <TodayPaneSearchField
            query={recentQuery}
            resultCount={recentItems.length}
            label="Search recent"
            onQueryChange={setRecentQuery}
            onClose={() => setRecentSearchOpen(false)}
            dataAttr="today-recent-search"
        />
    )
}
