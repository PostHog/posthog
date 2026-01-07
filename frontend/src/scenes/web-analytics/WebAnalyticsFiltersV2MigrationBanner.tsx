import { useValues } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

export const WebAnalyticsFiltersV2MigrationBanner = (): JSX.Element | null => {
    const { featureFlags } = useValues(featureFlagLogic)

    const useFiltersV2 = !!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_FILTERS_V2]
    const hasLegacyCondensedFlag = !!featureFlags[FEATURE_FLAGS.CONDENSED_FILTER_BAR]
    const shouldShowMigrationBanner = !useFiltersV2 && hasLegacyCondensedFlag

    if (!shouldShowMigrationBanner) {
        return null
    }

    return (
        <LemonBanner
            type="warning"
            dismissKey="web-analytics-filters-v2-migration"
            action={{
                children: 'Enable in feature previews',
                onClick: () => router.actions.push(urls.settings('user-feature-previews')),
            }}
        >
            Looking for the new filters experience? It is now a part of the Web Analytics Filters V2 early access
            feature! Enable it in feature previews to restore the experience and add some more fun features!
        </LemonBanner>
    )
}
