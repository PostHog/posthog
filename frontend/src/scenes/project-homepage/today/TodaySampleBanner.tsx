import { useActions, useValues } from 'kea'

import { Button, Item, ItemActions, ItemContent, ItemDescription } from '@posthog/quill'

import { todayLogic } from './todayLogic'

/** Says the page shows sample reports, so nobody mistakes them for the project's own. */
export function TodaySampleBanner(): JSX.Element | null {
    const { useSampleData } = useValues(todayLogic)
    const { setUseSampleData } = useActions(todayLogic)
    if (!useSampleData) {
        return null
    }
    return (
        <Item variant="outline" tone="info" size="sm" role="status">
            <ItemContent>
                <ItemDescription>
                    You’re looking at sample reports, not your project’s. They stay on until you turn them off.
                </ItemDescription>
            </ItemContent>
            <ItemActions>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setUseSampleData(false)}
                    data-attr="today-sample-data-off"
                >
                    Show my reports
                </Button>
            </ItemActions>
        </Item>
    )
}
