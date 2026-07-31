import { Link } from '@posthog/lemon-ui'

export function FeatureFlagPropertyNoResultsHint(): JSX.Element {
    return (
        <div className="text-center text-secondary max-w-100 text-xs">
            <p className="mb-1">
                Feature flags can only target person or group properties, cohorts, and other flags. They evaluate
                against a person or group, not an individual event, so event properties aren't available here.
            </p>
            <p className="mb-0">
                If this is only captured on events, send it along with the flag check using{' '}
                <Link to="https://posthog.com/docs/feature-flags/property-overrides" target="_blank">
                    property overrides
                </Link>
                .
            </p>
        </div>
    )
}
