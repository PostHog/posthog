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
                    className="-me-2 text-muted-foreground"
                    aria-label="New analytics"
                    data-attr="today-new-analytics-header"
                />
            }
        >
            <IconPlus />
        </NewAnalyticsMenu>
    )
}
