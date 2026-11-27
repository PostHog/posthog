import { IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { NewAnalyticsMenu } from 'scenes/analytics/NewAnalyticsMenu'

export function TodayNewAnalyticsButton(): JSX.Element {
    return (
        <NewAnalyticsMenu
            source="sidebar"
            trigger={
                <Button
                    size="icon"
                    variant="outline"
                    aria-label="New analytics"
                    data-attr="today-new-analytics-header"
                />
            }
        >
            <IconPlus />
        </NewAnalyticsMenu>
    )
}
