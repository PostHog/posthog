import { LemonBanner, Link } from '@posthog/lemon-ui'
import { Button, Item, ItemContent, ItemDescription } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

export function ErrorTrackingConfigurationMovedBanner(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <Item tone="info" size="sm">
                <ItemContent>
                    <ItemDescription>
                        <strong>Error tracking configuration has moved.</strong> Configurations for alerting,
                        suppression rules, spike detection, assignment rules, grouping rules, symbol sets, and releases
                        are now on the{' '}
                        <Button
                            variant="link"
                            size="inline"
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.errorTrackingConfiguration()} />}
                        >
                            Error tracking configuration
                        </Button>{' '}
                        page.
                    </ItemDescription>
                    <ItemDescription>
                        You can get there via the sidebar: <strong>Error tracking &rarr; Configuration</strong>.
                    </ItemDescription>
                </ItemContent>
            </Item>
        )
    }

    return (
        <LemonBanner type="info">
            <p>
                <strong>Error tracking configuration has moved.</strong> Configurations for alerting, suppression rules,
                spike detection, assignment rules, grouping rules, symbol sets, and releases are now on the{' '}
                <Link to={urls.errorTrackingConfiguration()}>Error tracking configuration</Link> page.
            </p>
            <p>
                You can get there via the sidebar: <strong>Error tracking &rarr; Configuration</strong>.
            </p>
        </LemonBanner>
    )
}
