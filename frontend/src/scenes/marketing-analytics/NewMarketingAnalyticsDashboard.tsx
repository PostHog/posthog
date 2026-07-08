import { LemonBanner } from '@posthog/lemon-ui'

// Scaffold for the redesigned marketing analytics dashboard, gated behind the
// `new-marketing-analytics-dashboard` feature flag. Intentionally a placeholder for now so the tab can
// merge early; the real content lands in follow-up PRs.
export function NewMarketingAnalyticsDashboard(): JSX.Element {
    return (
        <div className="mt-4">
            <LemonBanner type="info">The redesigned marketing analytics dashboard is coming soon.</LemonBanner>
        </div>
    )
}
