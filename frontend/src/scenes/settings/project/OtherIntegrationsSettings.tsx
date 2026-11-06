import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { IntegrationsList } from 'lib/integrations/IntegrationsList'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

export function OtherIntegrationsSettings(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <IntegrationsList
            omitKinds={
                featureFlags[FEATURE_FLAGS.WEB_GITLAB_INTEGRATION]
                    ? ['slack', 'github', 'linear', 'gitlab']
                    : ['slack', 'github', 'linear']
            }
            titleText=""
            emptyState={
                <div className="px-4 py-6 text-center text-sm text-secondary rounded border bg-surface-primary">
                    <p className="mb-1">No other integrations connected</p>
                    <p className="text-xs text-muted text-balance mb-0">
                        These connect from the product area that uses them:{' '}
                        <Link to={urls.destinations()}>pipeline destinations</Link>,{' '}
                        <Link to={urls.sources()}>data warehouse sources</Link>,{' '}
                        <Link to={urls.settings('environment-error-tracking', 'error-tracking-integrations')}>
                            error tracking
                        </Link>{' '}
                        and{' '}
                        <Link to={urls.settings('environment-marketing-analytics', 'marketing-settings')}>
                            marketing analytics
                        </Link>
                        .
                    </p>
                </div>
            }
        />
    )
}
