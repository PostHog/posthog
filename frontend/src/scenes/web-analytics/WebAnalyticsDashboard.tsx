import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import React, { useState } from 'react'

import { IconExpand45, IconInfo, IconLineGraph, IconOpenSidebar, IconX } from '@posthog/icons'
import { LemonSegmentedButton, LemonSkeleton } from '@posthog/lemon-ui'

import { keyBinds } from 'lib/components/AppShortcuts/shortcuts'
import { useAppShortcut } from 'lib/components/AppShortcuts/useAppShortcut'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { VersionCheckerBanner } from 'lib/components/VersionChecker/VersionCheckerBanner'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonSegmentedSelect } from 'lib/lemon-ui/LemonSegmentedSelect/LemonSegmentedSelect'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { LemonTag } from 'lib/lemon-ui/LemonTag'
import { Link, PostHogComDocsURL } from 'lib/lemon-ui/Link/Link'
import { Popover } from 'lib/lemon-ui/Popover'
import { IconLink, IconOpenInNew, IconTableChart } from 'lib/lemon-ui/icons'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { isNotNil } from 'lib/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { addProductIntentForCrossSell } from 'lib/utils/product-intents'
import { Scene } from 'scenes/sceneTypes'
import { QuickSurveyModal } from 'scenes/surveys/QuickSurveyModal'
import { QuickSurveyType } from 'scenes/surveys/quick-create/types'
import { teamLogic } from 'scenes/teamLogic'
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
import { ProductIntentContext, ProductKey, QuerySchema } from '~/queries/schema/schema-general'
import { InsightLogicProps, OnboardingStepKey, TeamPublicType, TeamType } from '~/types'

import { LiveWebAnalyticsMetrics } from './LiveMetricsDashboard/LiveWebAnalyticsMetrics'
import { WebAnalyticsExport } from './WebAnalyticsExport'
import { WebAnalyticsFilters } from './WebAnalyticsFilters'
import { HealthStatusTab, webAnalyticsHealthLogic } from './health'
import { webAnalyticsModalLogic } from './webAnalyticsModalLogic'

export const Tiles = (props: { tiles?: WebAnalyticsTile[]; compact?: boolean }): JSX.Element => {
    const { tiles: tilesFromProps, compact = false } = props
    const { tiles: tilesFromLogic, productTab } = useValues(webAnalyticsLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const tiles = tilesFromProps ?? tilesFromLogic
    const { featureFlags } = useValues(featureFlagLogic)

    const emptyOnboardingContent = getEmptyOnboardingContent(featureFlags, currentTeamLoading, currentTeam, productTab)

    return (
        <div
            className={clsx(
                'mt-4 grid grid-cols-1 md:grid-cols-2 xxl:grid-cols-3',
                compact ? 'gap-x-2 gap-y-2' : 'gap-x-4 gap-y-12'
            )}
        >
            {emptyOnboardingContent ??
                tiles.map((tile, i) => {
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
        <WebAnalyticsExport key="export-button" query={query} insightProps={insightProps} />,
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
                Open as new insight
            </LemonButton>
        ) : null,
        tile.canOpenModal !== false ? (
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
                insightProps: tab.insightProps,
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
        insightProps: InsightLogicProps
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

    const activeTabData = tabs.find((t) => t.id === activeTabId)

    const buttonsRow = [
        activeTab && activeTabData ? (
            <WebAnalyticsExport
                key="export-button"
                query={activeTabData.query}
                insightProps={activeTabData.insightProps}
            />
        ) : null,
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
        activeTab?.canOpenModal !== false ? (
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
const Filters = ({ tabs }: { tabs: JSX.Element }): JSX.Element | null => {
    const { productTab } = useValues(webAnalyticsLogic)
    switch (productTab) {
        case ProductTab.PAGE_REPORTS:
            return <PageReportsFilters tabs={tabs} />
        case ProductTab.HEALTH:
        case ProductTab.LIVE:
            return null
        default:
            return <WebAnalyticsFilters tabs={tabs} />
    }
}

const MainContent = (): JSX.Element => {
    const { productTab } = useValues(webAnalyticsLogic)

    if (productTab === ProductTab.PAGE_REPORTS) {
        return <PageReports />
    }

    if (productTab === ProductTab.HEALTH) {
        return <HealthStatusTab />
    }

    if (productTab === ProductTab.LIVE) {
        return <LiveWebAnalyticsMetrics />
    }

    return <Tiles />
}

const HealthTabLabel = (): JSX.Element => {
    const { hasUrgentIssues } = useValues(webAnalyticsHealthLogic)

    return (
        <div className="flex items-center gap-1.5">
            Installation Health
            {hasUrgentIssues && (
                <div className="w-4 h-4 rounded-full bg-danger flex items-center justify-center">
                    <span className="text-white text-xs font-bold">!</span>
                </div>
            )}
        </div>
    )
}

const healthTab = (featureFlags: FeatureFlagsSet): { key: ProductTab; label: JSX.Element; link: string }[] => {
    if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_HEALTH_TAB]) {
        return []
    }

    return [
        {
            key: ProductTab.HEALTH,
            label: <HealthTabLabel />,
            link: '/web/health',
        },
    ]
}

const liveTab = (featureFlags: FeatureFlagsSet): { key: ProductTab; label: string; link: string }[] => {
    if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_LIVE_METRICS]) {
        return []
    }

    return [
        {
            key: ProductTab.LIVE,
            label: 'Live',
            link: '/web/live',
        },
    ]
}

const WebAnalyticsSurveyModal = (): JSX.Element | null => {
    const { surveyModalPath } = useValues(webAnalyticsLogic)
    const { closeSurveyModal } = useActions(webAnalyticsLogic)

    if (!surveyModalPath) {
        return null
    }

    return (
        <QuickSurveyModal
            context={{ type: QuickSurveyType.WEB_PATH, path: surveyModalPath }}
            isOpen={!!surveyModalPath}
            onCancel={closeSurveyModal}
            showFollowupToggle={true}
            modalTitle={`Survey users on ${surveyModalPath}`}
            info={`Shown to users who spend more than 15 seconds on URLs containing ${surveyModalPath}, once per unique user`}
        />
    )
}

export const WebAnalyticsDashboard = (): JSX.Element => {
    return (
        <BindLogic logic={webAnalyticsLogic} props={{}}>
            <BindLogic logic={dataNodeCollectionLogic} props={{ key: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
                <WebAnalyticsModal />
                <WebAnalyticsSurveyModal />
                <VersionCheckerBanner />
                <SceneContent className="WebAnalyticsDashboard">
                    <WebAnalyticsTabs />
                    {/* Empty fragment so tabs are not part of the sticky bar */}
                    <Filters tabs={<></>} />

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

    // Tab switching shortcuts
    useAppShortcut({
        name: 'WebAnalyticsTab1',
        keybind: [keyBinds.tab1],
        intent: 'Web analytics tab',
        interaction: 'function',
        callback: () => setProductTab(ProductTab.ANALYTICS),
        scope: Scene.WebAnalytics,
    })
    useAppShortcut({
        name: 'WebAnalyticsTab2',
        keybind: [keyBinds.tab2],
        intent: 'Web vitals tab',
        interaction: 'function',
        callback: () => setProductTab(ProductTab.WEB_VITALS),
        scope: Scene.WebAnalytics,
    })
    useAppShortcut({
        name: 'WebAnalyticsTab3',
        keybind: [keyBinds.tab3],
        intent: 'Page reports tab',
        interaction: 'function',
        callback: () => setProductTab(ProductTab.PAGE_REPORTS),
        scope: Scene.WebAnalytics,
    })
    useAppShortcut({
        name: 'WebAnalyticsTab4',
        keybind: [keyBinds.tab4],
        intent: 'Health tab',
        interaction: 'function',
        callback: () => setProductTab(ProductTab.HEALTH),
        scope: Scene.WebAnalytics,
        disabled: !featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_HEALTH_TAB],
    })

    const handleShare = (): void => {
        void copyToClipboard(window.location.href, 'link')
    }

    return (
        <LemonTabs<ProductTab>
            activeKey={productTab}
            onChange={setProductTab}
            tabs={[
                { key: ProductTab.ANALYTICS, label: 'Web analytics', link: '/web' },
                { key: ProductTab.WEB_VITALS, label: 'Web vitals', link: '/web/web-vitals' },
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
                ...liveTab(featureFlags),
                ...healthTab(featureFlags),
            ]}
            sceneInset
            className="-mt-4"
            rightSlot={
                !featureFlags[FEATURE_FLAGS.CONDENSED_FILTER_BAR] && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconLink fontSize="16" />}
                        tooltip="Share"
                        tooltipPlacement="top"
                        onClick={handleShare}
                        data-attr="web-analytics-share-button"
                    />
                )
            }
        />
    )
}

const WebVitalsEmptyState = (): JSX.Element => {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)

    return (
        <div className="col-span-full w-full">
            <ProductIntroduction
                productName="Web Vitals"
                productKey={ProductKey.WEB_ANALYTICS}
                thingName="web vital"
                isEmpty={true}
                titleOverride="Enable web vitals to get started"
                description="Track Core Web Vitals like LCP, FID, and CLS to understand your site's performance. 
                Enabling this will capture performance metrics from your visitors, which counts towards your event quota.
                You can always disable this feature in the settings."
                docsURL="https://posthog.com/docs/web-analytics/web-vitals"
                actionElementOverride={
                    <LemonButton
                        type="primary"
                        onClick={() => updateCurrentTeam({ autocapture_web_vitals_opt_in: true })}
                        data-attr="web-vitals-enable"
                        disabledReason={currentTeam ? undefined : 'Loading...'}
                    >
                        Enable web vitals
                    </LemonButton>
                }
            />
        </div>
    )
}

const getEmptyOnboardingContent = (
    featureFlags: FeatureFlagsSet,
    currentTeamLoading: boolean,
    currentTeam: TeamType | TeamPublicType | null,
    productTab: ProductTab
): JSX.Element | null => {
    if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_EMPTY_ONBOARDING]) {
        return null
    }

    if (currentTeamLoading && !currentTeam) {
        return <LemonSkeleton className="col-span-full w-full" />
    }

    if (productTab === ProductTab.ANALYTICS && !currentTeam?.ingested_event) {
        return (
            <div className="col-span-full w-full">
                <ProductIntroduction
                    productName="Web Analytics"
                    productKey={ProductKey.WEB_ANALYTICS}
                    thingName="event"
                    isEmpty={true}
                    titleOverride="Nothing to investigate yet!"
                    description="Install PostHog on your site or app to start capturing events. Head to the installation guide to get set up in just a few minutes."
                    actionElementOverride={
                        <div className="flex items-center gap-2">
                            <LemonButton
                                type="primary"
                                to={urls.onboarding(ProductKey.WEB_ANALYTICS, OnboardingStepKey.INSTALL)}
                                data-attr="web-analytics-onboarding"
                            >
                                Open installation guide
                            </LemonButton>
                            <span className="text-muted-alt">or</span>
                            <Link target="_blank" to="/web/web-vitals">
                                Set up web vitals while you wait
                            </Link>
                        </div>
                    }
                />
            </div>
        )
    }

    if (productTab === ProductTab.WEB_VITALS && !currentTeam?.autocapture_web_vitals_opt_in) {
        return <WebVitalsEmptyState />
    }

    return null
}
