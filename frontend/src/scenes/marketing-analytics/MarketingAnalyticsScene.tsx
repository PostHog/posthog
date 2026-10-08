import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconGear, IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSwitch, LemonTabs, Spinner, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { MaxTool } from 'scenes/max/MaxTool'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { QueryTile } from 'scenes/web-analytics/common'
import { PagePerformance } from 'scenes/web-analytics/PagePerformance'
import { PagePerformanceFilters } from 'scenes/web-analytics/PagePerformanceFilters'
import { pagePerformanceLogic } from 'scenes/web-analytics/pagePerformanceLogic'
import { AttributionTab } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTab'
import { RetentionTab } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/RetentionTab/RetentionTab'
import { UtmAuditTab } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/UtmAuditTab/UtmAuditTab'
import { WebQuery } from 'scenes/web-analytics/tiles/WebAnalyticsTile'
import { webAnalyticsFilterLogic } from 'scenes/web-analytics/webAnalyticsFilterLogic'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ProductKey } from '~/queries/schema/schema-general'

import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'
import { DetectedSources } from 'products/marketing_analytics/frontend/dashboard/DetectedSources'
import { NewMarketingAnalyticsDashboard } from 'products/marketing_analytics/frontend/dashboard/NewMarketingAnalyticsDashboard'
import { SearchConsoleSource } from 'products/marketing_analytics/frontend/dashboard/SearchConsoleSource'
import { SourceSetupPanel } from 'products/marketing_analytics/frontend/dashboard/SourceSetupPanel'
import { marketingAnalyticsEmptyState } from 'products/marketing_analytics/frontend/emptyState/marketingAnalyticsEmptyState'
import { SearchPerformanceTab } from 'products/marketing_analytics/frontend/search/SearchPerformanceTab'
import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { LegacyOAuthReconnectBanner } from '../web-analytics/tabs/marketing-analytics/frontend/components/LegacyOAuthReconnectBanner'
import { MarketingAnalyticsFilters } from '../web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsFilters/MarketingAnalyticsFilters'
import { MarketingAnalyticsSourceStatusBanner } from '../web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsSourceStatusBanner'
import { IntegrationSettingsModal } from '../web-analytics/tabs/marketing-analytics/frontend/components/settings/IntegrationSettingsModal'
import {
    MarketingAnalyticsTab,
    SETUP_ABSORBED_TABS,
    marketingAnalyticsLogic,
} from '../web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'
import {
    MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    marketingAnalyticsTilesLogic,
} from '../web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'
import { setupPlanLogic } from '../web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'
import { marketingOnboardingLogic } from './Onboarding/marketingOnboardingLogic'
import { Onboarding } from './Onboarding/Onboarding'
import { SetupTab } from './Setup/SetupTab'

export const scene: SceneExport = {
    component: MarketingAnalyticsScene,
    logic: marketingAnalyticsLogic,
    productKey: ProductKey.MARKETING_ANALYTICS,
    emptyState: marketingAnalyticsEmptyState,
}

const QueryTileItem = ({ tile }: { tile: QueryTile }): JSX.Element => {
    const { query, title, layout, insightProps, control, showIntervalSelect } = tile

    return (
        <div
            className={clsx(
                'col-span-1 row-span-1 flex flex-col',
                layout.colSpanClassName ?? 'md:col-span-6',
                layout.rowSpanClassName ?? 'md:row-span-1',
                layout.orderWhenLargeClassName ?? '2xl:order-12',
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
    const {
        hasSources,
        dataWarehouseSources,
        hasSyncedMarketingSources,
        nativeSources,
        validExternalTables,
        loading,
        isAdPerformance,
        includeConversionGoals,
    } = useValues(marketingAnalyticsLogic)
    const { setAdPerformanceConversionGoals } = useActions(marketingAnalyticsLogic)
    const { loadSources } = useActions(sourcesDataLogic)
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)
    const { tiles: marketingTiles } = useValues(marketingAnalyticsTilesLogic)
    const { showOnboarding } = useValues(marketingOnboardingLogic)
    const { completeOnboarding } = useActions(marketingOnboardingLogic)

    // Reload sources on every navigation to this scene so newly configured
    // data warehouse sources are picked up without a full page refresh
    useEffect(() => {
        loadSources()
    }, [loadSources])

    const hasSearchConsole =
        !!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS] &&
        !!dataWarehouseSources?.results.some((source) => source.source_type === 'GoogleSearchConsole')
    const hasConfiguredSources = nativeSources.length > 0 || validExternalTables.length > 0 || hasSearchConsole

    useEffect(() => {
        if (!isAdPerformance && !loading && hasConfiguredSources && showOnboarding) {
            completeOnboarding()
        }
    }, [loading, hasConfiguredSources, showOnboarding, completeOnboarding, isAdPerformance])

    if (!isAdPerformance && !featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_MARKETING]) {
        return (
            <>
                <LemonBanner type="info">
                    You can enable marketing analytics in the feature preview settings{' '}
                    <Link to="https://app.posthog.com/settings/user-feature-previews#marketing-analytics">here</Link>.
                </LemonBanner>
            </>
        )
    }

    if (loading && !dataWarehouseSources) {
        return (
            <>
                <h2 className="max-w-3xl w-full mx-auto mt-6 mb-0">Ad performance</h2>
                {featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_SOURCE_ONBOARDING] ? (
                    <SourceSetupPanel state="checking" />
                ) : (
                    <div className="flex justify-center p-8">
                        <Spinner />
                    </div>
                )}
                <SearchConsoleSource />
            </>
        )
    }

    if (!isAdPerformance && !hasConfiguredSources && showOnboarding) {
        return (
            <>
                <Onboarding completeOnboarding={completeOnboarding} />
            </>
        )
    }

    return (
        <>
            {isAdPerformance && conversion_goals.length > 0 && (
                <LemonSwitch
                    className="mt-4"
                    label="Include conversion goals"
                    checked={includeConversionGoals}
                    onChange={setAdPerformanceConversionGoals}
                    data-attr="marketing-ad-performance-conversion-goals"
                />
            )}
            <LegacyOAuthReconnectBanner />
            {hasSyncedMarketingSources && <MarketingAnalyticsSourceStatusBanner />}
            <h2
                className={
                    hasSyncedMarketingSources || hasSearchConsole ? 'mt-6 mb-0' : 'max-w-3xl w-full mx-auto mt-6 mb-0'
                }
            >
                Ad performance
            </h2>
            <DetectedSources compact={hasSearchConsole && !hasSyncedMarketingSources} />
            {!dataWarehouseSources?.results.some((source) =>
                ['GoogleAds', 'BingAds', 'GoogleSearchConsole'].includes(source.source_type)
            ) && <SearchConsoleSource />}
            {hasSources && hasSyncedMarketingSources && (
                <div className="mt-4 grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-x-4 gap-y-12">
                    {marketingTiles?.map((tile, i) => (
                        <QueryTileItem key={i} tile={tile} />
                    ))}
                </div>
            )}
        </>
    )
}

const MarketingAnalyticsContent = (): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { activeTab, hasSyncedMarketingSources, dataWarehouseSources } = useValues(marketingAnalyticsLogic)
    const { setActiveTab, setSetupSection } = useActions(marketingAnalyticsLogic)
    const { integrationSettingsModal } = useValues(marketingAnalyticsSettingsLogic)
    const { closeIntegrationSettingsModal } = useActions(marketingAnalyticsSettingsLogic)

    const hasConnectedSearchSource =
        !!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS] &&
        !!dataWarehouseSources?.results.some((source) =>
            ['GoogleAds', 'BingAds', 'GoogleSearchConsole'].includes(source.source_type)
        )

    // The redesigned dashboard replaces the current one under the same "Dashboard" tab when its flag is
    // on, so the eventual cutover is just flipping the flag — no tab rename, no extra tab key to strand.
    const dashboard = (
        <>
            {featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD] ? (
                <NewMarketingAnalyticsDashboard />
            ) : (
                <>
                    {hasSyncedMarketingSources && <MarketingAnalyticsFilters tabs={<></>} />}
                    <MarketingAnalyticsDashboard />
                    {hasConnectedSearchSource && (
                        <div className="mt-8">
                            <SearchPerformanceTab showSourceSuggestions={hasSyncedMarketingSources} />
                        </div>
                    )}
                </>
            )}
            {/* Both dashboards carry the campaign breakdown, whose mapping menus open this modal, so it
                is mounted beside them rather than inside one. It sits in the tab content, because Setup
                and Integration health mount their own copy off the same shared state. */}
            {integrationSettingsModal.integration && (
                <IntegrationSettingsModal
                    integrationName={integrationSettingsModal.integration}
                    isOpen={integrationSettingsModal.isOpen}
                    onClose={closeIntegrationSettingsModal}
                    initialTab={integrationSettingsModal.initialTab}
                    initialUtmValue={integrationSettingsModal.initialUtmValue}
                />
            )}
        </>
    )

    // Setup absorbs Integration health: while its flag is on, the audit lives inside
    // Setup as a section rather than as a second top-level tab, so there's one door to
    // "something is wrong with my setup" instead of two.
    const setupEnabled =
        !!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_SETUP] ||
        !!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD]

    // Setup absorbs the tabs it replaces, so a link or bookmark carrying one still lands
    // somewhere sensible. Here rather than in the logic because only the scene knows
    // whether Setup is rendering: with its flag off those tabs are still real and
    // resolve on their own. Above the early return below, since hooks have to run on
    // every render.
    const absorbed = setupEnabled ? SETUP_ABSORBED_TABS[activeTab] : undefined
    useEffect(() => {
        if (absorbed) {
            setActiveTab(MarketingAnalyticsTab.SETUP)
            setSetupSection(absorbed)
        }
    }, [absorbed, setActiveTab, setSetupSection])

    const tabs = [
        { key: MarketingAnalyticsTab.DASHBOARD, label: 'Dashboard', content: dashboard },
        ...(featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD]
            ? [
                  {
                      key: MarketingAnalyticsTab.AD_PERFORMANCE,
                      label: 'Ad performance',
                      content: (
                          <>
                              {hasSyncedMarketingSources && <MarketingAnalyticsFilters tabs={<></>} />}
                              <MarketingAnalyticsDashboard />
                              {hasConnectedSearchSource && (
                                  <div className="mt-8">
                                      <SearchPerformanceTab showSourceSuggestions={hasSyncedMarketingSources} />
                                  </div>
                              )}
                              {integrationSettingsModal.integration && (
                                  <IntegrationSettingsModal
                                      integrationName={integrationSettingsModal.integration}
                                      isOpen={integrationSettingsModal.isOpen}
                                      onClose={closeIntegrationSettingsModal}
                                      initialTab={integrationSettingsModal.initialTab}
                                      initialUtmValue={integrationSettingsModal.initialUtmValue}
                                  />
                              )}
                          </>
                      ),
                  },
              ]
            : []),
        ...(featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD]
            ? [
                  {
                      key: MarketingAnalyticsTab.PAGE_VISIBILITY,
                      label: 'Page visibility',
                      content: (
                          <BindLogic logic={webAnalyticsLogic} props={{ context: 'page-visibility' }}>
                              <BindLogic logic={webAnalyticsFilterLogic} props={{ context: 'page-visibility' }}>
                                  <BindLogic logic={pagePerformanceLogic} props={{ context: 'page-visibility' }}>
                                      <PagePerformanceFilters tabs={<></>} />
                                      <PagePerformance />
                                  </BindLogic>
                              </BindLogic>
                          </BindLogic>
                      ),
                  },
              ]
            : []),
        ...(!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD] &&
        featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_ATTRIBUTION]
            ? [
                  {
                      key: MarketingAnalyticsTab.ATTRIBUTION,
                      label: 'Attribution explorer',
                      content: <AttributionTab />,
                  },
              ]
            : []),
        ...(!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD] &&
        featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_RETENTION]
            ? [
                  {
                      key: MarketingAnalyticsTab.RETENTION,
                      label: 'Retention explorer',
                      content: <RetentionTab />,
                  },
              ]
            : []),
        ...(setupEnabled
            ? [{ key: MarketingAnalyticsTab.SETUP, label: 'Setup', content: <SetupTab /> }]
            : featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_UTM_AUDIT]
              ? [
                    {
                        key: MarketingAnalyticsTab.INTEGRATION_HEALTH,
                        label: 'Integration health',
                        content: <UtmAuditTab />,
                    },
                ]
              : []),
    ]

    // A stored tab can still name one no flag is rendering — a key persisted from before
    // a flag was turned off. Normalising the state rather than just what LemonTabs
    // highlights: `activeTab` also feeds the scene description and `?tab=`, so leaving it
    // invalid describes a tab you aren't on and writes it back into the URL on the next
    // filter change. Above the early return, since hooks run on every render.
    const tabIsRendered = tabs.some((tab) => tab.key === activeTab)
    useEffect(() => {
        if (!tabIsRendered && !absorbed) {
            setActiveTab(
                activeTab === MarketingAnalyticsTab.SEARCH_PERFORMANCE &&
                    featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD] &&
                    featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS]
                    ? MarketingAnalyticsTab.AD_PERFORMANCE
                    : MarketingAnalyticsTab.DASHBOARD
            )
        }
    }, [tabIsRendered, absorbed, setActiveTab, activeTab, featureFlags])
    const selectedTab = tabIsRendered ? activeTab : MarketingAnalyticsTab.DASHBOARD

    // Only surface the tab bar once a secondary tab is enabled; otherwise show the dashboard directly.
    if (tabs.length === 1) {
        return dashboard
    }

    return (
        <LemonTabs activeKey={selectedTab} onChange={(key) => setActiveTab(key as MarketingAnalyticsTab)} tabs={tabs} />
    )
}

const TAB_DESCRIPTIONS: Record<string, string> = {
    [MarketingAnalyticsTab.SEARCH_PERFORMANCE]:
        'Explore paid and organic search performance across keywords, queries and landing pages.',
    [MarketingAnalyticsTab.PAGE_VISIBILITY]:
        'Explore page traffic, Google search visibility, AI referrals, crawler activity, and conversions.',
    [MarketingAnalyticsTab.AD_PERFORMANCE]: 'Compare ad spend, clicks and impressions across your connected platforms.',
    [MarketingAnalyticsTab.DASHBOARD]:
        'Analyze your marketing performance across integrations: spend, impressions, conversions, ROAS, and more metrics.',
    [MarketingAnalyticsTab.ATTRIBUTION]:
        'Compare how each attribution model credits your conversions, to see which marketing you might be over or under valuing.',
    [MarketingAnalyticsTab.RETENTION]:
        "See how well the users each channel brings you stick around, grouped by the channel that first brought them in. Each percentage is the share of a cohort seen again, measured against the cohort's original size.",
    [MarketingAnalyticsTab.INTEGRATION_HEALTH]:
        'Check that your ad platform campaigns are properly linked to UTM tracking in PostHog.',
    [MarketingAnalyticsTab.SETUP]:
        'Everything Marketing analytics needs to work: connected ad platforms, conversion goals, UTM mapping and attribution.',
}

const MarketingAnalyticsAIToolWrapper = ({ children }: { children: React.ReactNode }): JSX.Element => {
    const { activeTab, dateFilter, integrationFilter, compareFilter } = useValues(marketingAnalyticsLogic)
    const { conversion_goals, marketingAnalyticsConfig } = useValues(marketingAnalyticsSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const aiEnabled =
        !!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_AI] && activeTab !== MarketingAnalyticsTab.PAGE_VISIBILITY

    // Shared context for every Marketing analytics Max tool — consumed by
    // MARKETING_CONTEXT_PROMPT in products/marketing_analytics/backend/max_tools.py.
    const maxContext = {
        current_filters: { integrationFilter, compareFilter },
        current_date_range: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
        custom_source_mappings_count: Object.keys(marketingAnalyticsConfig?.custom_source_mappings || {}).length,
        campaign_name_mappings_count: Object.keys(marketingAnalyticsConfig?.campaign_name_mappings || {}).length,
        existing_goal_count: (conversion_goals || []).length,
    }

    // Register the follow-up tools so Max can actually call them when the
    // diagnostic recommends them. Only `marketing_diagnose_setup` gets the
    // visible MaxTool button below — the rest are data tools with no UI anchor.
    useMaxTool({ identifier: 'marketing_explain_conversion_goal', context: maxContext, active: aiEnabled })
    useMaxTool({ identifier: 'marketing_list_conversion_goals', context: maxContext, active: aiEnabled })
    useMaxTool({ identifier: 'marketing_list_data_sources', context: maxContext, active: aiEnabled })
    useMaxTool({ identifier: 'marketing_audit_utm', context: maxContext, active: aiEnabled })
    useMaxTool({ identifier: 'marketing_suggest_conversion_goals', context: maxContext, active: aiEnabled })
    useMaxTool({ identifier: 'marketing_suggest_utm_mappings', context: maxContext, active: aiEnabled })

    useAttachedContext(
        [
            {
                type: 'marketing_analytics_filters',
                value: JSON.stringify({ integrationFilter, compareFilter }),
                label: 'Current filters',
            },
            {
                type: 'marketing_analytics_date_range',
                value: JSON.stringify({ date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo }),
                label: 'Date range',
            },
            {
                type: 'marketing_analytics_config_counts',
                value: JSON.stringify({
                    custom_source_mappings_count: Object.keys(marketingAnalyticsConfig?.custom_source_mappings || {})
                        .length,
                    campaign_name_mappings_count: Object.keys(marketingAnalyticsConfig?.campaign_name_mappings || {})
                        .length,
                    existing_goal_count: (conversion_goals || []).length,
                }),
                label: 'Marketing config counts',
            },
        ],
        { active: aiEnabled }
    )

    return (
        <MaxTool
            identifier="marketing_diagnose_setup"
            active={aiEnabled}
            context={maxContext}
            contextDescription={{
                text: 'Marketing analytics setup',
                icon: <IconSparkles />,
            }}
            initialMaxPrompt="Diagnose my marketing analytics setup"
            suggestions={[
                'Diagnose my marketing analytics setup',
                'Why are events showing as non-integrated?',
                'Suggest custom_source_mappings for unmatched UTM values',
                'Which custom events would make good conversion goals?',
                'List my conversion goals and their last-30d performance',
            ]}
        >
            <>{children}</>
        </MaxTool>
    )
}

export function MarketingAnalyticsScene(): JSX.Element {
    useValues(setupPlanLogic)
    const { activeTab } = useValues(marketingAnalyticsLogic)

    return (
        <BindLogic logic={marketingAnalyticsLogic} props={{}}>
            <BindLogic logic={dataNodeCollectionLogic} props={{ key: MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID }}>
                <SceneContent className="MarketingAnalyticsDashboard">
                    <SceneTitleSection
                        name={sceneConfigurations[Scene.MarketingAnalytics]?.name || 'Marketing analytics'}
                        description={
                            TAB_DESCRIPTIONS[activeTab] || sceneConfigurations[Scene.MarketingAnalytics]?.description
                        }
                        resourceType={{
                            type: sceneConfigurations[Scene.MarketingAnalytics]?.iconType || 'marketing_analytics',
                        }}
                        actions={
                            <>
                                <LemonButton type="tertiary" size="small" id="marketing-analytics-feedback-button">
                                    Send feedback
                                </LemonButton>
                                <LemonButton
                                    to="https://posthog.com/docs/web-analytics/marketing-analytics"
                                    type="secondary"
                                    targetBlank
                                    size="small"
                                    data-attr="marketing-analytics-docs-button"
                                >
                                    Documentation
                                </LemonButton>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconGear />}
                                    to={urls.settings('environment-marketing-analytics', 'marketing-settings')}
                                    data-attr="marketing-analytics-settings-button"
                                >
                                    Settings
                                </LemonButton>
                            </>
                        }
                    />
                    <MarketingAnalyticsAIToolWrapper>
                        <MarketingAnalyticsContent />
                    </MarketingAnalyticsAIToolWrapper>
                </SceneContent>
            </BindLogic>
        </BindLogic>
    )
}
