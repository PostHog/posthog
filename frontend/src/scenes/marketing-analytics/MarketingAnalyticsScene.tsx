import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { VersionCheckerBanner } from 'lib/components/VersionChecker/VersionCheckerBanner'
import { FilmCameraHog } from 'lib/components/hedgehogs'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'
import { QueryTile } from 'scenes/web-analytics/common'
import { NonIntegratedConversionsTable } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/NonIntegratedConversionsTable/NonIntegratedConversionsTable'
import { WebQuery } from 'scenes/web-analytics/tiles/WebAnalyticsTile'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ProductKey } from '~/queries/schema/schema-general'

import { MarketingAnalyticsFilters } from '../web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsFilters/MarketingAnalyticsFilters'
import { MarketingAnalyticsSourceStatusBanner } from '../web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsSourceStatusBanner'
import { marketingAnalyticsLogic } from '../web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import {
    MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    marketingAnalyticsTilesLogic,
} from '../web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'

export const scene: SceneExport = {
    component: MarketingAnalyticsScene,
    logic: marketingAnalyticsLogic,
    productKey: ProductKey.MARKETING_ANALYTICS,
}

const QueryTileItem = ({ tile }: { tile: QueryTile }): JSX.Element => {
    const { query, title, layout, insightProps, control, showIntervalSelect } = tile

    return (
        <div
            className={clsx(
                'col-span-1 row-span-1 flex flex-col',
                layout.colSpanClassName ?? 'md:col-span-6',
                layout.rowSpanClassName ?? 'md:row-span-1',
                layout.orderWhenLargeClassName ?? 'xxl:order-12',
                layout.className
            )}
        >
            {title && (
                <div className="flex flex-row items-center mb-3">
                    <h2>{title}</h2>
                </div>
            )}

            <WebQuery
                attachTo={marketingAnalyticsLogic}
                uniqueKey={`MarketingAnalytics.${tile.tileId}`}
                query={query}
                insightProps={insightProps}
                control={control}
                showIntervalSelect={showIntervalSelect}
                tileId={tile.tileId}
            />
        </div>
    )
}

const MarketingAnalyticsDashboard = (): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { validExternalTables, validNativeSources, loading } = useValues(marketingAnalyticsLogic)
    const { tiles: marketingTiles } = useValues(marketingAnalyticsTilesLogic)

    const feedbackBanner = (
        <LemonBanner type="info" action={{ children: 'Send feedback', id: 'marketing-analytics-feedback-button' }}>
            Marketing analytics is in beta. Please let us know what you'd like to see here and/or report any issues
            directly to us!
        </LemonBanner>
    )

    let component: JSX.Element | null = null
    if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_MARKETING]) {
        component = (
            <LemonBanner type="info">
                You can enable marketing analytics in the feature preview settings{' '}
                <Link to="https://app.posthog.com/settings/user-feature-previews#marketing-analytics">here</Link>.
            </LemonBanner>
        )
    } else if (loading) {
        component = <LemonSkeleton />
    } else if (validExternalTables.length === 0 && validNativeSources.length === 0) {
        component = (
            <ProductIntroduction
                productName="Marketing analytics"
                productKey={ProductKey.MARKETING_ANALYTICS}
                thingName="marketing integration"
                titleOverride="Add your first marketing integration"
                description="To enable marketing analytics, you need to integrate your marketing data sources. You can do this in the settings by adding a native (like Google Ads) or non-native (from a bucket like S3) source."
                action={() => window.open(urls.settings('environment-marketing-analytics'), '_blank')}
                isEmpty={true}
                docsURL="https://posthog.com/docs/web-analytics/marketing-analytics"
                customHog={FilmCameraHog}
            />
        )
    } else {
        // if the user has sources configured and the feature flag is enabled, show the marketing tiles
        component = (
            <div className="mt-4 grid grid-cols-1 md:grid-cols-2 xxl:grid-cols-3 gap-x-4 gap-y-12">
                {marketingTiles?.map((tile, i) => (
                    <QueryTileItem key={i} tile={tile} />
                ))}
                <NonIntegratedConversionsTable />
            </div>
        )
    }

    return (
        <>
            {feedbackBanner}
            <MarketingAnalyticsSourceStatusBanner />
            {component}
        </>
    )
}

export function MarketingAnalyticsScene(): JSX.Element {
    return (
        <BindLogic logic={marketingAnalyticsLogic} props={{}}>
            <BindLogic logic={dataNodeCollectionLogic} props={{ key: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
                <VersionCheckerBanner />
                <SceneContent className="MarketingAnalyticsDashboard">
                    <SceneTitleSection
                        name={sceneConfigurations[Scene.MarketingAnalytics]?.name || 'Marketing analytics'}
                        description={sceneConfigurations[Scene.MarketingAnalytics]?.description}
                        resourceType={{
                            type: sceneConfigurations[Scene.MarketingAnalytics]?.iconType || 'marketing_analytics',
                        }}
                    />
                    <MarketingAnalyticsFilters tabs={<></>} />
                    <MarketingAnalyticsDashboard />
                </SceneContent>
            </BindLogic>
        </BindLogic>
    )
}
