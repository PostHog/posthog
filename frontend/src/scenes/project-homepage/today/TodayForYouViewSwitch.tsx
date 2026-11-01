import { useActions, useValues } from 'kea'

import { ToggleGroup, ToggleGroupItem } from '@posthog/quill'

import { type TodayForYouView, todayLogic } from './todayLogic'

export function TodayForYouViewSwitch(): JSX.Element | null {
    const { forYouReady, forYouRows, forYouView } = useValues(todayLogic)
    const { setForYouView } = useActions(todayLogic)
    if (!forYouReady || forYouRows.rows.length === 0) {
        return null
    }
    return (
        <ToggleGroup
            size="sm"
            aria-label="View"
            value={[forYouView]}
            onValueChange={([view]) => view && setForYouView(view as TodayForYouView)}
        >
            <ToggleGroupItem value="list" data-attr="today-for-you-view-list">
                List
            </ToggleGroupItem>
            <ToggleGroupItem value="feed" data-attr="today-for-you-view-feed">
                Feed
            </ToggleGroupItem>
        </ToggleGroup>
    )
}
