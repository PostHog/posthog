import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import React, { useState } from 'react'

import { IconExpand45, IconInfo, IconLineGraph, IconOpenSidebar, IconX } from '@posthog/icons'
import { LemonBanner, LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { VersionCheckerBanner } from 'lib/components/VersionChecker/VersionCheckerBanner'
import { FilmCameraHog } from 'lib/components/hedgehogs'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSegmentedSelect } from 'lib/lemon-ui/LemonSegmentedSelect/LemonSegmentedSelect'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link, PostHogComDocsURL } from 'lib/lemon-ui/Link/Link'
import { Popover } from 'lib/lemon-ui/Popover'
import { IconOpenInNew, IconTableChart } from 'lib/lemon-ui/icons'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isNotNil } from 'lib/utils'
import { ProductIntentContext, addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { urls } from 'scenes/urls'
import { PageReports, PageReportsFilters } from 'scenes/web-analytics/PageReports'
import { WebAnalyticsHealthCheck } from 'scenes/web-analytics/WebAnalyticsHealthCheck'
import { WebAnalyticsModal } from 'scenes/web-analytics/WebAnalyticsModal'
import {
    ProductTab,
    QueryTile,
    SectionTile,
    TabsTile,
    TileId,
    TileVisualizationOption,
    WEB_ANALYTICS_DATA_COLLECTION_NODE_ID,
    WebAnalyticsTile,
} from 'scenes/web-analytics/common'
import { WebAnalyticsErrorTrackingTile } from 'scenes/web-analytics/tiles/WebAnalyticsErrorTracking'
import { WebAnalyticsRecordingsTile } from 'scenes/web-analytics/tiles/WebAnalyticsRecordings'
import { WebQuery } from 'scenes/web-analytics/tiles/WebAnalyticsTile'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { QuerySchema } from '~/queries/schema/schema-general'
import { ProductKey } from '~/types'

import { WebAnalyticsFilters } from './WebAnalyticsFilters'
import { WebAnalyticsPageReportsCTA } from './WebAnalyticsPageReportsCTA'
import { MarketingAnalyticsFilters } from './tabs/marketing-analytics/frontend/components/MarketingAnalyticsFilters/MarketingAnalyticsFilters'
import { marketingAnalyticsLogic } from './tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { webAnalyticsModalLogic } from './webAnalyticsModalLogic'

export const Tiles = (props: { tiles?: WebAnalyticsTile[]; compact?: boolean }): JSX.Element => {
    const { tiles: tilesFromProps, compact = false } = props
    const { tiles: tilesFromLogic } = useValues(webAnalyticsLogic)

    const tiles = tilesFromProps ?? tilesFromLogic

    return (
        <div
            className={clsx(
                'mt-4 grid grid-cols-1 md:grid-cols-2 xxl:grid-cols-3',
                compact ? 'gap-x-2 gap-y-2' : 'gap-x-4 gap-y-12'
            )}
        >
            {tiles.map((tile, i) => {
                if (tile.kind === 'query') {
                    return <QueryTileItem key={i} tile={tile} />
                } else if (tile.kind === 'tabs') {
                    return <TabsTileItem key={i} tile={tile} />
                } else if (tile.kind === 'replay') {
                    return <WebAnalyticsRecordingsTile key={i} tile={tile} />
                } else if (tile.kind === 'error_tracking') {
                    return <WebAnalyticsErrorTrackingTile key={i} tile={tile} />
                } else if (tile.kind === 'section') {
                    return <SectionTileItem key={i} tile={tile} />
                }
                return null
            })}
        </div>
    )
}

const QueryTileItem = ({ tile }: { tile: QueryTile }): JSX.Element => {
    const { query, title, layout, insightProps, control, showIntervalSelect, docs } = tile

    const { openModal } = useActions(webAnalyticsModalLogic)
    const { getNewInsightUrl } = useValues(webAnalyticsLogic)

    const buttonsRow = [
        tile.canOpenInsight ? (
            <LemonButton
                key="open-insight-button"
                to={getNewInsightUrl(tile.tileId)}
                icon={<IconOpenInNew />}
                size="small"
                type="secondary"
                onClick={() => {
                    void addProductIntentForCrossSell({
                        from: ProductKey.WEB_ANALYTICS,
                        to: ProductKey.PRODUCT_ANALYTICS,
                        intent_context: ProductIntentContext.WEB_ANALYTICS_INSIGHT,
                    })
                }}
            >
                Open as new Insight
            </LemonButton>
        ) : null,
        tile.canOpenModal ? (
            <LemonButton
                key="open-modal-button"
                onClick={() => openModal(tile.tileId)}
                icon={<IconExpand45 />}
                size="small"
                type="secondary"
            >
                Show more
            </LemonButton>
        ) : null,
    ].filter(isNotNil)

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
                    {docs && <LearnMorePopover url={docs.url} title={docs.title} description={docs.description} />}
                </div>
            )}

            <WebQuery
                attachTo={webAnalyticsLogic}
                uniqueKey={`WebAnalytics.${tile.tileId}`}
                query={query}
                insightProps={insightProps}
                control={control}
                showIntervalSelect={showIntervalSelect}
                tileId={tile.tileId}
            />

            {buttonsRow.length > 0 ? (
                <div className="flex justify-end my-2 deprecated-space-x-2">{buttonsRow}</div>
            ) : null}
        </div>
    )
}

const TabsTileItem = ({ tile }: { tile: TabsTile }): JSX.Element => {
    const { layout } = tile

    const { getNewInsightUrl } = useValues(webAnalyticsLogic)

    return (
        <WebTabs
            className={clsx(
                'col-span-1 row-span-1',
                layout.colSpanClassName || 'md:col-span-1',
                layout.rowSpanClassName || 'md:row-span-1',
                layout.orderWhenLargeClassName || 'xxl:order-12',
                layout.className
            )}
            activeTabId={tile.activeTabId}
            setActiveTabId={tile.setTabId}
            tabs={tile.tabs.map((tab) => ({
                id: tab.id,
                content: (
                    <WebQuery
                        attachTo={webAnalyticsLogic}
                        uniqueKey={`WebAnalytics.${tile.tileId}.${tab.id}`}
                        key={tab.id}
                        query={tab.query}
                        showIntervalSelect={tab.showIntervalSelect}
                        control={tab.control}
                        insightProps={tab.insightProps}
                        tileId={tile.tileId}
                    />
                ),
                linkText: tab.linkText,
                title: tab.title,
                canOpenModal: !!tab.canOpenModal,
                canOpenInsight: !!tab.canOpenInsight,
                query: tab.query,
                docs: tab.docs,
            }))}
            tileId={tile.tileId}
            getNewInsightUrl={getNewInsightUrl}
        />
    )
}

export const SectionTileItem = ({ tile, separator }: { tile: SectionTile; separator?: boolean }): JSX.Element => {
    return (
        <div className="col-span-full">
            {tile.title && <h2 className="text-lg font-semibold mb-4">{tile.title}</h2>}
            <div className={tile.layout.className ? `grid ${tile.layout.className} mb-4` : 'mb-4'}>
                {tile.tiles.map((subTile, i) => {
                    if (subTile.kind === 'query') {
                        return (
                            <div key={`${subTile.tileId}-${i}`} className="col-span-1">
                                <QueryTileItem tile={subTile} />
                            </div>
                        )
                    }
                    return null
                })}
            </div>
            {separator && <LemonDivider className="my-3" />}
        </div>
    )
}

export const WebTabs = ({
    className,
    activeTabId,
    tabs,
    setActiveTabId,
    getNewInsightUrl,
    tileId,
}: {
    className?: string
    activeTabId: string
    tabs: {
        id: string
        title: string | JSX.Element
        linkText: string | JSX.Element
        content: React.ReactNode
        canOpenModal?: boolean
        canOpenInsight: boolean
        query: QuerySchema
        docs: LearnMorePopoverProps | undefined
    }[]
    setActiveTabId: (id: string) => void
    getNewInsightUrl: (tileId: TileId, tabId: string) => string | undefined
    tileId: TileId
}): JSX.Element => {
    const activeTab = tabs.find((t) => t.id === activeTabId)
    const newInsightUrl = getNewInsightUrl(tileId, activeTabId)

    const { openModal } = useActions(webAnalyticsModalLogic)
    const { setTileVisualization } = useActions(webAnalyticsLogic)
    const { tileVisualizations } = useValues(webAnalyticsLogic)
    const visualization = tileVisualizations[tileId]

    const isVisualizationToggleEnabled = [TileId.SOURCES, TileId.DEVICES, TileId.PATHS].includes(tileId)

    const buttonsRow = [
        activeTab?.canOpenInsight && newInsightUrl ? (
            <LemonButton
                key="open-insight-button"
                to={newInsightUrl}
                icon={<IconOpenInNew />}
                size="small"
                type="secondary"
                onClick={() => {
                    void addProductIntentForCrossSell({
                        from: ProductKey.WEB_ANALYTICS,
                        to: ProductKey.PRODUCT_ANALYTICS,
                        intent_context: ProductIntentContext.WEB_ANALYTICS_INSIGHT,
                    })
                }}
            >
                Open as new Insight
            </LemonButton>
        ) : null,
        activeTab?.canOpenModal ? (
            <LemonButton
                key="open-modal-button"
                onClick={() => openModal(tileId, activeTabId)}
                icon={<IconExpand45 />}
                size="small"
                type="secondary"
            >
                Show more
            </LemonButton>
        ) : null,
    ].filter(isNotNil)

    return (
        <div className={clsx(className, 'flex flex-col')}>
            <div className="flex flex-row items-center self-stretch mb-3">
                <h2 className="flex-1 m-0 flex flex-row ml-1">
                    {activeTab?.title}
                    {activeTab?.docs && (
                        <LearnMorePopover
                            url={activeTab.docs.url}
                            title={activeTab.docs.title}
                            description={activeTab.docs.description}
                        />
                    )}
                </h2>

                {isVisualizationToggleEnabled && (
                    <LemonSegmentedButton
                        value={visualization || 'table'}
                        onChange={(value) => setTileVisualization(tileId, value as TileVisualizationOption)}
                        options={[
                            {
                                value: 'table',
                                icon: <IconTableChart />,
                            },
                            {
                                value: 'graph',
                                icon: <IconLineGraph />,
                            },
                        ]}
                        size="small"
                        className="mr-2"
                    />
                )}

                <LemonSegmentedSelect
                    shrinkOn={7}
                    size="small"
                    disabled={false}
                    value={activeTabId}
                    dropdownMatchSelectWidth={false}
                    onChange={setActiveTabId}
                    options={tabs.map(({ id, linkText }) => ({ value: id, label: linkText }))}
                />
            </div>
            <div className="flex-1 flex flex-col">{activeTab?.content}</div>
            {buttonsRow.length > 0 ? (
                <div className="flex justify-end my-2 deprecated-space-x-2">{buttonsRow}</div>
            ) : null}
        </div>
    )
}

export interface LearnMorePopoverProps {
    url?: PostHogComDocsURL
    title: string
    description: string | JSX.Element
}

export const LearnMorePopover = ({ url, title, description }: LearnMorePopoverProps): JSX.Element => {
    const [isOpen, setIsOpen] = useState(false)

    return (
        <Popover
            visible={isOpen}
            onClickOutside={() => setIsOpen(false)}
            overlay={
                <div className="p-4 max-w-160 max-h-160 overflow-auto">
                    <div className="flex flex-row w-full">
                        <h2 className="flex-1">{title}</h2>
                        <LemonButton
                            targetBlank
                            type="tertiary"
                            onClick={() => setIsOpen(false)}
                            size="small"
                            icon={<IconX />}
                        />
                    </div>
                    <div className="text-sm text-gray-700 dark:text-white">{description}</div>
                    {url && (
                        <div className="flex justify-end mt-4">
                            <LemonButton
                                to={url}
                                onClick={() => setIsOpen(false)}
                                targetBlank={true}
                                sideIcon={<IconOpenSidebar />}
                            >
                                Learn more
                            </LemonButton>
                        </div>
                    )}
                </div>
            }
        >
            <LemonButton onClick={() => setIsOpen(!isOpen)} size="small" icon={<IconInfo />} className="ml-1 mb-1" />
        </Popover>
    )
}

// We're switching the filters based on the productTab right now so it is abstracted here
// until we decide if we want to keep the same components/states for both tabs
const Filters = ({ tabs }: { tabs: JSX.Element }): JSX.Element => {
    const { productTab } = useValues(webAnalyticsLogic)
    switch (productTab) {
        case ProductTab.PAGE_REPORTS:
            return <PageReportsFilters tabs={tabs} />
        case ProductTab.MARKETING:
            return <MarketingAnalyticsFilters tabs={tabs} />
        default:
            return <WebAnalyticsFilters tabs={tabs} />
    }
}

const MainContent = (): JSX.Element => {
    const { productTab } = useValues(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    if (productTab === ProductTab.PAGE_REPORTS && featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_PAGE_REPORTS]) {
        return <PageReports />
    }

    if (productTab === ProductTab.MARKETING) {
        return <MarketingDashboard />
    }

    return <Tiles />
}

const MarketingDashboard = (): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { validExternalTables, validNativeSources, loading } = useValues(marketingAnalyticsLogic)

    const feedbackBanner = (
        <LemonBanner
            type="info"
            dismissKey="marketing-analytics-beta-banner"
            className="mb-2 mt-4"
            action={{ children: 'Send feedback', id: 'marketing-analytics-feedback-button' }}
        >
            Marketing analytics is in beta. Please let us know what you'd like to see here and/or report any issues
            directly to us!
        </LemonBanner>
    )

    let component: JSX.Element | null = null
    if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_MARKETING]) {
        // fallback in case the user is able to access the page but the feature flag is not enabled
        component = (
            <LemonBanner type="info">
                You can enable marketing analytics in the feature preview settings{' '}
                <Link to="https://app.posthog.com/settings/user-feature-previews#marketing-analytics">here</Link>.
            </LemonBanner>
        )
    } else if (loading) {
        component = <LemonSkeleton />
    } else if (validExternalTables.length === 0 && validNativeSources.length === 0) {
        // if the user has no sources configured, show a warning instead of an empty state
        component = (
            <ProductIntroduction
                productName="Marketing Analytics"
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
        // if the user has sources configured and the feature flag is enabled, show the tiles
        component = <Tiles />
    }

    return (
        <>
            {feedbackBanner}
            {component}
        </>
    )
}

const pageReportsTab = (featureFlags: FeatureFlagsSet): { key: ProductTab; label: JSX.Element; link: string }[] => {
    if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_PAGE_REPORTS]) {
        return []
    }
    return [
        {
            key: ProductTab.PAGE_REPORTS,
            label: (
                <div className="flex items-center gap-1">
                    Page reports
                    <LemonTag type="warning" className="uppercase">
                        Beta
                    </LemonTag>
                </div>
            ),
            link: '/web/page-reports',
        },
    ]
}

const marketingTab = (featureFlags: FeatureFlagsSet): { key: ProductTab; label: JSX.Element; link: string }[] => {
    if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_MARKETING]) {
        return []
    }
    return [
        {
            key: ProductTab.MARKETING,
            label: (
                <div className="flex items-center gap-1">
                    Marketing
                    <LemonTag type="warning" className="uppercase">
                        Beta
                    </LemonTag>
                </div>
            ),
            link: '/web/marketing',
        },
    ]
}

export const WebAnalyticsDashboard = (): JSX.Element => {
    return (
        <BindLogic logic={webAnalyticsLogic} props={{}}>
            <BindLogic logic={dataNodeCollectionLogic} props={{ key: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
                <WebAnalyticsModal />
                <VersionCheckerBanner />
                <SceneContent className="WebAnalyticsDashboard w-full flex flex-col">
                    <WebAnalyticsTabs />
                    {/* Empty fragment so tabs are not part of the sticky bar */}
                    <Filters tabs={<></>} />

                    <WebAnalyticsPageReportsCTA />
                    <WebAnalyticsHealthCheck />
                    <MainContent />
                </SceneContent>
            </BindLogic>
        </BindLogic>
    )
}

const WebAnalyticsTabs = (): JSX.Element => {
    const { productTab } = useValues(webAnalyticsLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const { setProductTab } = useActions(webAnalyticsLogic)

    return (
        <LemonTabs<ProductTab>
            activeKey={productTab}
            onChange={setProductTab}
            tabs={[
                { key: ProductTab.ANALYTICS, label: 'Web analytics', link: '/web' },
                { key: ProductTab.WEB_VITALS, label: 'Web vitals', link: '/web/web-vitals' },
                ...pageReportsTab(featureFlags),
                ...marketingTab(featureFlags),
            ]}
            sceneInset
            className="-mt-4"
        />
    )
}
