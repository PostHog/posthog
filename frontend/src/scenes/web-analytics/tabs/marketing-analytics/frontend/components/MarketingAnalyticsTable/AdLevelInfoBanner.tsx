import { useActions } from 'kea'
import { useRef } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { usePageVisibilityCb } from 'lib/hooks/usePageVisibility'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { MarketingAnalyticsDrillDownLevel } from '~/queries/schema/schema-general'

import { marketingAnalyticsLogic, NativeSourceHierarchyStatus } from '../../logic/marketingAnalyticsLogic'
import { nativeSourceDisplayLabel } from '../../logic/utils'

type AdLevelInfoBannerProps = {
    drillDownLevel: MarketingAnalyticsDrillDownLevel
    sourcesHierarchyStatus: NativeSourceHierarchyStatus[]
}

/** Empty-state banner shown at AD_GROUP / AD drill-down. Per source: fully-syncing
 * sources are hidden; sync-fixable ones (schemas exist but aren't enabled) get a
 * deep-link to the sync settings; platform-unsupported ones get a no-link heads-up.
 */
export const AdLevelInfoBanner = ({ drillDownLevel, sourcesHierarchyStatus }: AdLevelInfoBannerProps): JSX.Element => {
    const { refreshSourcesForBanner } = useActions(marketingAnalyticsLogic)
    const isAdGroup = drillDownLevel === MarketingAnalyticsDrillDownLevel.AdGroup
    const fixableSources = sourcesHierarchyStatus.filter((s) =>
        isAdGroup ? !s.supportsAdGroup && !s.adGroupUnsupported : !s.supportsAd && !s.adUnsupported
    )
    const platformUnsupportedSources = sourcesHierarchyStatus.filter((s) =>
        isAdGroup ? s.adGroupUnsupported : s.adUnsupported
    )
    const dismissKey = isAdGroup ? 'marketing-analytics-ad-group-level-info' : 'marketing-analytics-ad-level-info'

    // The fix-it link opens settings in a new tab, so re-fetch sources on
    // visibility-change to clear stale gaps when the user returns. Gated on
    // `hasFixableSources` to avoid an API call on every alt-tab once green.
    const skipFirstVisibilityCall = useRef(true)
    const hasFixableSources = fixableSources.length > 0
    usePageVisibilityCb((isVisible) => {
        if (skipFirstVisibilityCall.current) {
            skipFirstVisibilityCall.current = false
            return
        }
        if (isVisible && hasFixableSources) {
            refreshSourcesForBanner({ reloadTilesAfter: true })
        }
    })

    return (
        <LemonBanner type={fixableSources.length > 0 ? 'warning' : 'info'} dismissKey={dismissKey}>
            <div>
                Ad group and ad metrics come directly from your ad platform. Conversion goals aren't shown at this level
                because events can't be attributed to a specific ad.
            </div>
            {fixableSources.length > 0 && (
                <div className="mt-2">
                    <div className="font-semibold">
                        {fixableSources.length === 1
                            ? 'One source needs more schemas synced to appear here:'
                            : 'These sources need more schemas synced to appear here:'}
                    </div>
                    <ul className="mt-1 list-disc pl-5">
                        {fixableSources.map((source) => {
                            const missing = isAdGroup ? source.missingForAdGroup : source.missingForAd
                            return (
                                <li key={source.sourceId}>
                                    <Link
                                        to={`${urls.dataWarehouseSource(`managed-${source.sourceId}`)}?ph_utm_source=ma`}
                                        target="_blank"
                                    >
                                        {nativeSourceDisplayLabel(source.sourceType)}
                                    </Link>
                                    : enable{' '}
                                    {missing.map((schema, idx) => (
                                        <span key={schema}>
                                            <code>{schema}</code>
                                            {idx < missing.length - 1 ? ', ' : ''}
                                        </span>
                                    ))}
                                </li>
                            )
                        })}
                    </ul>
                </div>
            )}
            {platformUnsupportedSources.length > 0 && (
                <div className="mt-2">
                    {platformUnsupportedSources.map((s) => nativeSourceDisplayLabel(s.sourceType)).join(', ')}{' '}
                    {platformUnsupportedSources.length === 1 ? "doesn't" : "don't"} yet expose{' '}
                    {isAdGroup ? 'ad-group' : 'ad'}-level data through PostHog's data warehouse import — coming in a
                    follow-up.
                </div>
            )}
        </LemonBanner>
    )
}
