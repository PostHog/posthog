import { Link } from '@posthog/lemon-ui'

import { FeatureFlagSettings as BasicFeatureFlagSettings } from 'scenes/feature-flags/FeatureFlagSettings'
import { urls } from 'scenes/urls'

export function FeatureFlagSettings(): JSX.Element {
    return (
        <>
            <p>
                Configure default behavior for feature flags. Flags can be managed on the{' '}
                <Link to={urls.featureFlags()}>feature flags page</Link>.
            </p>

            <BasicFeatureFlagSettings />
        </>
    )
}
