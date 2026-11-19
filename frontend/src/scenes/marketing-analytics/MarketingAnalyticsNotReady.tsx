import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

export function MarketingAnalyticsNotReady({ autoRefreshing }: { autoRefreshing: boolean }): JSX.Element {
    return (
        <LemonBanner type="info" data-attr="marketing-analytics-not-ready">
            {autoRefreshing
                ? 'Your marketing analytics is being prepared. This page updates on its own when the data is ready.'
                : 'Your marketing analytics is taking longer than usual to prepare. Refresh the page in a few minutes to check again.'}
        </LemonBanner>
    )
}
