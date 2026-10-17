import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

export function MarketingAnalyticsNotReady(): JSX.Element {
    return (
        <LemonBanner type="info" data-attr="marketing-analytics-not-ready">
            Your marketing analytics is being prepared. This report refreshes about once an hour, so it should appear
            shortly. This page updates automatically when it's ready.
        </LemonBanner>
    )
}
