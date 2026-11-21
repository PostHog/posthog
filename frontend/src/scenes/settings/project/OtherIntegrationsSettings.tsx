import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'
import { Button, Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IntegrationsList } from 'lib/integrations/IntegrationsList'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

export function OtherIntegrationsSettings(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const quillLink = (to: string, label: string): JSX.Element => (
        <Button variant="link" size="inline" nativeButton={false} render={<LinkPrimitive to={to} />}>
            {label}
        </Button>
    )

    return (
        <IntegrationsList
            omitKinds={
                featureFlags[FEATURE_FLAGS.WEB_GITLAB_INTEGRATION]
                    ? ['slack', 'github', 'linear', 'gitlab']
                    : ['slack', 'github', 'linear']
            }
            titleText=""
            emptyState={
                todayRailNav ? (
                    <Empty>
                        <EmptyHeader>
                            <EmptyTitle>No other integrations connected</EmptyTitle>
                            <EmptyDescription>
                                These connect from the product area that uses them:{' '}
                                {quillLink(urls.destinations(), 'pipeline destinations')},{' '}
                                {quillLink(urls.sources(), 'data warehouse sources')},{' '}
                                {quillLink(
                                    urls.settings('environment-error-tracking', 'error-tracking-integrations'),
                                    'error tracking'
                                )}{' '}
                                and{' '}
                                {quillLink(
                                    urls.settings('environment-marketing-analytics', 'marketing-settings'),
                                    'marketing analytics'
                                )}
                                .
                            </EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                ) : (
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
                )
            }
        />
    )
}
