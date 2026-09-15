import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconCursor, IconPeople, IconRetention, IconTarget, IconTrends } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCollapse, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { CompareFilter } from 'lib/components/CompareFilter/CompareFilter'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { FEATURE_FLAGS } from 'lib/constants'
import { useLocalStorage } from 'lib/hooks/useLocalStorage'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS } from 'scenes/web-analytics/common'
import { AttributionTab } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTab'
import { AttributionTable } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/AttributionTab/AttributionTable'
import { RetentionTab } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/components/RetentionTab/RetentionTab'
import {
    MarketingAnalyticsTab,
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import { marketingAttributionLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAttributionLogic'
import { BREAKDOWN_LABELS } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingBreakdown'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'
import { webAnalyticsDataTableQueryContext } from 'scenes/web-analytics/tiles/WebAnalyticsTile'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { OverviewMetricCardGrid } from '~/queries/nodes/OverviewGrid/OverviewMetricCardGrid'
import { labelFromKey } from '~/queries/nodes/WebOverview/WebOverview'
import { Query } from '~/queries/Query/Query'
import {
    MarketingAnalyticsAttributionBreakdown,
    NodeKind,
    WebOverviewQuery,
    WebOverviewQueryResponse,
    WebStatsBreakdown,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { suggestionsForSection } from './Setup/sectionRouting'
import { SuggestionRow } from './Setup/SuggestionRow'

const TRAFFIC_BREAKDOWNS = [
    { value: WebStatsBreakdown.InitialChannelType, label: 'Channel' },
    { value: WebStatsBreakdown.InitialUTMSource, label: 'UTM source' },
    { value: WebStatsBreakdown.InitialUTMCampaign, label: 'Campaign' },
    { value: WebStatsBreakdown.InitialUTMMedium, label: 'Medium' },
    { value: WebStatsBreakdown.InitialReferringDomain, label: 'Referring domain' },
    { value: WebStatsBreakdown.InitialPage, label: 'Landing page' },
]

const QUERY_CONTEXT: QueryContext = {
    ...webAnalyticsDataTableQueryContext,
    columns: {
        ...webAnalyticsDataTableQueryContext.columns,
        visitors: { ...webAnalyticsDataTableQueryContext.columns?.visitors, renderTitle: () => <>Visitors</> },
        views: { ...webAnalyticsDataTableQueryContext.columns?.views, renderTitle: () => <>Pageviews</> },
        bounce_rate: { ...webAnalyticsDataTableQueryContext.columns?.bounce_rate, renderTitle: () => <>Bounce rate</> },
    },
}

// Scaffold for the redesigned marketing analytics dashboard, gated behind the
// `new-marketing-analytics-dashboard` feature flag.
export function NewMarketingAnalyticsDashboard(): JSX.Element {
    const [selectedSection, setSelectedSection] = useState('acquisition')
    const [trafficBreakdown, setTrafficBreakdown] = useState(WebStatsBreakdown.InitialChannelType)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const sections = [
        {
            key: 'acquisition',
            title: 'Acquisition',
            description: 'Visitors, sessions and pageviews',
            icon: <IconPeople />,
        },
        {
            key: 'engagement',
            title: 'Engagement',
            description: 'Session duration and bounce rate',
            icon: <IconCursor />,
        },
        ...(featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_RETENTION]
            ? [
                  {
                      key: 'retention',
                      title: 'Retention',
                      description: 'Returning visitors by cohort',
                      icon: <IconRetention />,
                  },
              ]
            : []),
        ...(featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_ATTRIBUTION]
            ? [
                  {
                      key: 'conversion',
                      title: 'Conversion',
                      description: 'Goals and conversion paths',
                      icon: <IconTarget />,
                  },
                  {
                      key: 'revenue',
                      title: 'Revenue',
                      description: 'Revenue by attribution model',
                      icon: <IconTrends />,
                  },
              ]
            : []),
    ]
    const activeSection = sections.some(({ key }) => key === selectedSection) ? selectedSection : 'acquisition'
    const isTraffic = activeSection === 'acquisition' || activeSection === 'engagement'
    const { revenueGoals, selectedRevenueGoalId, revenueQuery, breakdownBy } = useValues(marketingAttributionLogic)
    const { setRevenueGoalId, setBreakdownBy } = useActions(marketingAttributionLogic)
    const { dateFilter, compareFilter, shouldFilterTestAccounts } = useValues(marketingAnalyticsLogic)
    const { setDates, setCompareFilter, setActiveTab, setSetupSection } = useActions(marketingAnalyticsLogic)
    const { setupPlan, setupPlanLoading, visibleSuggestions } = useValues(setupPlanLogic)
    const { loadSetupPlan, reviewSuggestion } = useActions(setupPlanLogic)
    const [sourcesExpanded, setSourcesExpanded] = useLocalStorage('marketing-source-suggestions-expanded', true)
    const sourceSuggestions = visibleSuggestions.filter((suggestion) => suggestion.kind === 'connect_source')
    const reviewSources = (): void => {
        setSetupSection(SetupSection.SOURCES)
        setActiveTab(MarketingAnalyticsTab.SETUP)
    }

    const [goalsExpanded, setGoalsExpanded] = useLocalStorage('marketing-goal-suggestions-expanded', true)
    const goalSuggestions = suggestionsForSection(visibleSuggestions, SetupSection.CONVERSION_GOALS)
    const reviewGoals = (): void => {
        setSetupSection(SetupSection.CONVERSION_GOALS)
        setActiveTab(MarketingAnalyticsTab.SETUP)
    }

    const requestedSetupPlan = useRef(false)
    useEffect(() => {
        if (!setupPlan && !setupPlanLoading && !requestedSetupPlan.current) {
            requestedSetupPlan.current = true
            loadSetupPlan()
        }
    }, [setupPlan, setupPlanLoading, loadSetupPlan])

    const dateRange = { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo }
    const query: WebOverviewQuery = {
        kind: NodeKind.WebOverviewQuery,
        dateRange,
        compareFilter,
        filterTestAccounts: shouldFilterTestAccounts,
        properties: [],
        tags: MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS,
    }
    const overviewLogic = dataNodeLogic({ query, key: 'marketing-acquisition-overview' })
    const { response, responseLoading, responseError } = useValues(overviewLogic)
    const { loadData } = useActions(overviewLogic)
    const overview = response as WebOverviewQueryResponse | undefined

    return (
        <div className="mt-4 flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-2">
                <DateFilter dateFrom={dateFilter.dateFrom} dateTo={dateFilter.dateTo} onChange={setDates} />
                {isTraffic && (
                    <>
                        <CompareFilter compareFilter={compareFilter} updateCompareFilter={setCompareFilter} />
                        <LemonButton size="small" loading={responseLoading} onClick={() => loadData('force_async')}>
                            Reload summary
                        </LemonButton>
                    </>
                )}
            </div>
            {sourceSuggestions.length > 0 && (
                <div className="border rounded relative">
                    <LemonButton className="absolute right-2 top-0 z-10" size="small" onClick={reviewSources}>
                        Review in Setup
                    </LemonButton>
                    <LemonCollapse
                        embedded
                        size="small"
                        activeKey={sourcesExpanded ? 'sources' : null}
                        onChange={(key) => setSourcesExpanded(key !== null)}
                        panels={[
                            {
                                key: 'sources',
                                header: {
                                    children: `Suggested ad sources (${sourceSuggestions.length})`,
                                    className: 'pr-36',
                                },
                                content: sourceSuggestions.map((suggestion) => (
                                    <SuggestionRow
                                        key={suggestion.id}
                                        suggestion={suggestion}
                                        currentSection={SetupSection.SOURCES}
                                        onReview={(item) => {
                                            reviewSources()
                                            reviewSuggestion(item)
                                        }}
                                    />
                                )),
                            },
                        ]}
                    />
                </div>
            )}
            {goalSuggestions.length > 0 && (
                <div className="border rounded relative">
                    <LemonButton className="absolute right-2 top-0 z-10" size="small" onClick={reviewGoals}>
                        Review in Setup
                    </LemonButton>
                    <LemonCollapse
                        embedded
                        size="small"
                        activeKey={goalsExpanded ? 'goals' : null}
                        onChange={(key) => setGoalsExpanded(key !== null)}
                        panels={[
                            {
                                key: 'goals',
                                header: {
                                    children: `Suggested conversion goals (${goalSuggestions.length})`,
                                    className: 'pr-36',
                                },
                                content: goalSuggestions.map((suggestion) => (
                                    <SuggestionRow
                                        key={suggestion.id}
                                        suggestion={suggestion}
                                        currentSection={SetupSection.CONVERSION_GOALS}
                                        onReview={(item) => {
                                            reviewGoals()
                                            reviewSuggestion(item)
                                        }}
                                    />
                                )),
                            },
                        ]}
                    />
                </div>
            )}
            <nav aria-label="Dashboard sections" className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
                {sections.map(({ key, title, description, icon }) => (
                    <LemonButton
                        key={key}
                        type={activeSection === key ? 'primary' : 'secondary'}
                        onClick={() => setSelectedSection(key)}
                        aria-pressed={activeSection === key}
                        aria-controls="marketing-dashboard-section"
                        className="h-full"
                        fullWidth
                    >
                        <div className="flex flex-col gap-2 py-2 text-left">
                            <span className="flex items-center gap-2 text-lg font-semibold">
                                {icon}
                                {title}
                            </span>
                            <span className="font-normal">{description}</span>
                        </div>
                    </LemonButton>
                ))}
            </nav>
            <div id="marketing-dashboard-section" className="flex flex-col gap-4">
                {isTraffic &&
                    (responseError ? (
                        <LemonBanner
                            type="error"
                            action={{ children: 'Retry', onClick: () => loadData('force_async') }}
                        >
                            Could not load traffic metrics. Try again.
                        </LemonBanner>
                    ) : (
                        [
                            { key: 'acquisition', title: 'Acquisition', keys: ['visitors', 'sessions', 'views'] },
                            { key: 'engagement', title: 'Engagement', keys: ['session duration', 'bounce rate'] },
                        ]
                            .filter(({ key }) => key === activeSection)
                            .map(({ title, keys }) => (
                                <section key={title} className="flex flex-col gap-2" aria-label={title}>
                                    <h2 className="mb-0">{title}</h2>
                                    <OverviewMetricCardGrid
                                        items={keys.flatMap((key) =>
                                            (overview?.results?.filter((item) => item.key === key) ?? []).map(
                                                (item) => ({
                                                    ...item,
                                                    value: item.value,
                                                })
                                            )
                                        )}
                                        loading={responseLoading}
                                        numSkeletons={keys.length}
                                        samplingRate={overview?.samplingRate}
                                        preComputeStrategy={overview?.preComputeStrategy}
                                        labelFromKey={labelFromKey}
                                    />
                                </section>
                            ))
                    ))}
                {activeSection === 'conversion' && (
                    <section aria-label="Conversion" className="flex flex-col gap-2">
                        <h2 className="mb-0">Conversion</h2>
                        <AttributionTab />
                    </section>
                )}
                {activeSection === 'retention' && (
                    <section aria-label="Retention" className="flex flex-col gap-2">
                        <h2 className="mb-0">Retention</h2>
                        <p className="text-secondary mb-0">
                            Follow visitors acquired in the selected date range across subsequent periods.
                        </p>
                        <RetentionTab />
                    </section>
                )}
                {activeSection === 'revenue' && (
                    <section aria-label="Revenue" className="flex flex-col gap-4">
                        <h2 className="mb-0">Revenue</h2>
                        {currentTeamLoading || !currentTeam ? (
                            <LemonSkeleton className="h-40" />
                        ) : revenueQuery ? (
                            <>
                                <div className="flex flex-wrap items-center gap-2">
                                    <DateFilter
                                        dateFrom={dateFilter.dateFrom}
                                        dateTo={dateFilter.dateTo}
                                        onChange={setDates}
                                    />
                                    <LemonSelect
                                        value={selectedRevenueGoalId}
                                        onChange={(value) => value && setRevenueGoalId(value)}
                                        options={revenueGoals.map((goal) => ({
                                            value: goal.conversion_goal_id,
                                            label: goal.conversion_goal_name,
                                        }))}
                                        data-attr="marketing-revenue-goal"
                                    />
                                    <LemonSelect
                                        value={breakdownBy}
                                        onChange={setBreakdownBy}
                                        options={Object.values(MarketingAnalyticsAttributionBreakdown).map((value) => ({
                                            value,
                                            label: BREAKDOWN_LABELS[value],
                                        }))}
                                        data-attr="marketing-revenue-breakdown"
                                    />
                                </div>
                                <p className="text-secondary mb-0">
                                    Compare attributed value across models for one revenue goal at a time.
                                </p>
                                <AttributionTable
                                    metric="revenue"
                                    query={revenueQuery}
                                    attachTo={marketingAnalyticsLogic}
                                />
                            </>
                        ) : (
                            <LemonBanner
                                type="info"
                                action={{
                                    children: 'Review in Setup',
                                    onClick: () => {
                                        setSetupSection(SetupSection.CONVERSION_GOALS)
                                        setActiveTab(MarketingAnalyticsTab.SETUP)
                                    },
                                }}
                            >
                                Choose an event or action goal that sums an amount and mark it as Revenue in Setup.
                            </LemonBanner>
                        )}
                    </section>
                )}
                {isTraffic && (
                    <>
                        <div className="flex items-center gap-2">
                            <span>Breakdown by</span>
                            <LemonSelect
                                value={trafficBreakdown}
                                onChange={setTrafficBreakdown}
                                options={TRAFFIC_BREAKDOWNS}
                                aria-label="Traffic breakdown"
                            />
                        </div>
                        <Query
                            query={{
                                kind: NodeKind.DataTableNode,
                                source: {
                                    kind: NodeKind.WebStatsTableQuery,
                                    breakdownBy: trafficBreakdown,
                                    dateRange,
                                    compareFilter,
                                    filterTestAccounts: shouldFilterTestAccounts,
                                    includeBounceRate: activeSection === 'engagement',
                                    properties: [],
                                    limit: 25,
                                    tags: MARKETING_ANALYTICS_DEFAULT_QUERY_TAGS,
                                },
                                hiddenColumns: activeSection === 'engagement' ? ['context.columns.views'] : [],
                                full: true,
                                embedded: false,
                                showOpenEditorButton: false,
                            }}
                            context={{ ...QUERY_CONTEXT, compareFilter }}
                            readOnly
                        />
                    </>
                )}
            </div>
        </div>
    )
}
