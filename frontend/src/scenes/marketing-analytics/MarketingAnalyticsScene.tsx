import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconGear, IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTabs, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { MaxTool } from 'scenes/max/MaxTool'
import { useMaxTool } from 'scenes/max/useMaxTool'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { QueryTile } from 'scenes/web-analytics/common'
import { NonIntegratedConversionsTable } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/NonIntegratedConversionsTable/NonIntegratedConversionsTable'
import { UtmAuditTab } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/UtmAuditTab/UtmAuditTab'
import { WebQuery } from 'scenes/web-analytics/tiles/WebAnalyticsTile'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'
import { ProductKey } from '~/queries/schema/schema-general'

import { sourcesDataLogic } from 'products/data_warehouse/frontend/shared/logics/sourcesDataLogic'
import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { MarketingAnalyticsFilters } from '../web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsFilters/MarketingAnalyticsFilters'
import { MarketingAnalyticsSourceStatusBanner } from '../web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsSourceStatusBanner'
import {
    MarketingAnalyticsTab,
    marketingAnalyticsLogic,
} from '../web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { marketingAnalyticsSettingsLogic } from '../web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsSettingsLogic'
import {
    MARKETING_ANALYTICS_DATA_COLLECTION_NODE_ID,
    marketingAnalyticsTilesLogic,
} from '../web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsTilesLogic'
import { marketingOnboardingLogic } from './Onboarding/marketingOnboardingLogic'
import { Onboarding } from './Onboarding/Onboarding'

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
    const { hasSources, hasNoConfiguredSources, loading } = useValues(marketingAnalyticsLogic)
    const { loadSources } = useActions(sourcesDataLogic)
    const { conversion_goals } = useValues(marketingAnalyticsSettingsLogic)
    const { tiles: marketingTiles } = useValues(marketingAnalyticsTilesLogic)
    const { showOnboarding, currentStep } = useValues(marketingOnboardingLogic)
    const { completeOnboarding, resetOnboarding } = useActions(marketingOnboardingLogic)

    // Reload sources on every navigation to this scene so newly configured
    // data warehouse sources are picked up without a full page refresh
    useEffect(() => {
        loadSources()
    }, [loadSources])

    // Auto-complete onboarding if user already has sources and conversion goals configured,
    // but only when not actively on the conversion-goals step (let the user click "Continue")
    useEffect(() => {
        if (
            !loading &&
            hasSources &&
            conversion_goals.length > 0 &&
            showOnboarding &&
            currentStep !== 'conversion-goals'
        ) {
            completeOnboarding()
        }
    }, [loading, hasSources, conversion_goals, showOnboarding, currentStep, completeOnboarding])

    // Reset onboarding if user truly has no configured sources (handles session/project changes).
    // Uses hasNoConfiguredSources which guards against premature evaluation while tables are loading.
    useEffect(() => {
        if (hasNoConfiguredSources && !showOnboarding) {
            resetOnboarding()
        }
    }, [loading, hasSources, showOnboarding, resetOnboarding]) // oxlint-disable-line react-hooks/exhaustive-deps

    const feedbackBanner = (
        <LemonBanner
            type="info"
            action={{
                children: 'Send feedback',
                id: 'marketing-analytics-feedback-button',
            }}
            className="mt-4"
        >
            Marketing analytics is in beta. Please let us know what you'd like to see here and/or report any issues
            directly to us!
        </LemonBanner>
    )

    if (!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_MARKETING]) {
        return (
            <>
                {feedbackBanner}
                <LemonBanner type="info">
                    You can enable marketing analytics in the feature preview settings{' '}
                    <Link to="https://app.posthog.com/settings/user-feature-previews#marketing-analytics">here</Link>.
                </LemonBanner>
            </>
        )
    }

    if (loading) {
        return (
            <>
                {feedbackBanner}
                <LemonSkeleton />
            </>
        )
    }

    // Show onboarding if user hasn't completed it yet
    if (showOnboarding) {
        return (
            <>
                {feedbackBanner}
                <Onboarding completeOnboarding={completeOnboarding} />
            </>
        )
    }

    return (
        <>
            {feedbackBanner}
            <MarketingAnalyticsSourceStatusBanner />
            <div className="mt-4 grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-3 gap-x-4 gap-y-12">
                {marketingTiles?.map((tile, i) => (
                    <QueryTileItem key={i} tile={tile} />
                ))}
                <NonIntegratedConversionsTable />
            </div>
        </>
    )
}

const MarketingAnalyticsContent = (): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)
    const { activeTab } = useValues(marketingAnalyticsLogic)
    const { setActiveTab } = useActions(marketingAnalyticsLogic)

    const showIntegrationHealth = !!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_UTM_AUDIT]

    return (
        <>
            {showIntegrationHealth ? (
                <LemonTabs
                    activeKey={activeTab}
                    onChange={(key) => setActiveTab(key as MarketingAnalyticsTab)}
                    tabs={[
                        {
                            key: MarketingAnalyticsTab.DASHBOARD,
                            label: 'Dashboard',
                            content: (
                                <>
                                    <MarketingAnalyticsFilters tabs={<></>} />
                                    <MarketingAnalyticsDashboard />
                                </>
                            ),
                        },
                        {
                            key: MarketingAnalyticsTab.INTEGRATION_HEALTH,
                            label: 'Integration health',
                            content: <UtmAuditTab />,
                        },
                    ]}
                />
            ) : (
                <>
                    <MarketingAnalyticsFilters tabs={<></>} />
                    <MarketingAnalyticsDashboard />
                </>
            )}
        </>
    )
}

const TAB_DESCRIPTIONS: Record<string, string> = {
    [MarketingAnalyticsTab.DASHBOARD]:
        'Analyze your marketing performance across integrations: spend, impressions, conversions, ROAS, and more metrics.',
    [MarketingAnalyticsTab.INTEGRATION_HEALTH]:
        'Check that your ad platform campaigns are properly linked to UTM tracking in PostHog.',
}

const MarketingAnalyticsAIToolWrapper = ({ children }: { children: React.ReactNode }): JSX.Element => {
    const { dateFilter, integrationFilter, compareFilter } = useValues(marketingAnalyticsLogic)
    const { conversion_goals, marketingAnalyticsConfig } = useValues(marketingAnalyticsSettingsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const aiEnabled = !!featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_AI]

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
