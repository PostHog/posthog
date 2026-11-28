import { Item, ItemContent, ItemDescription } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

export function MarketingAnalyticsNotReady({ autoRefreshing }: { autoRefreshing: boolean }): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const message = autoRefreshing
        ? 'Your marketing analytics is being prepared. This page updates on its own when the data is ready.'
        : 'Your marketing analytics is taking longer than usual to prepare. Refresh the page in a few minutes to check again.'

    if (todayRailNav) {
        return (
            <Item tone="info" size="sm" data-attr="marketing-analytics-not-ready">
                <ItemContent>
                    <ItemDescription>{message}</ItemDescription>
                </ItemContent>
            </Item>
        )
    }

    return (
        <LemonBanner type="info" data-attr="marketing-analytics-not-ready">
            {message}
        </LemonBanner>
    )
}
