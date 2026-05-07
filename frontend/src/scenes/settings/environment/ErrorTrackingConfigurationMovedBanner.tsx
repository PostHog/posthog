import { LemonBanner, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export function ErrorTrackingConfigurationMovedBanner(): JSX.Element {
    return (
        <LemonBanner type="info">
            <p>
                <strong>Error tracking configuration has moved.</strong> Configurations for alerting, suppression rules,
                spike detection, auto assignment, custom grouping, symbol sets, and releases are now on the{' '}
                <Link to={urls.errorTrackingConfiguration()}>Error tracking configuration</Link> page.
            </p>
            <p>
                You can get there via the sidebar: <strong>Error tracking &rarr; Configuration</strong>.
            </p>
        </LemonBanner>
    )
}
