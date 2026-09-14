import { useActions, useMountedLogic, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { useChartTheme } from 'lib/charts/hooks'
import { seriesColor } from 'lib/charts/utils/theme'
import { urls } from 'scenes/urls'

import { DataTableNode, InsightVizNode, ProductKey } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { OnboardingStepKey } from '~/types'

import { SearchAndAiLoading } from 'products/web_analytics/frontend/searchAndAi/SearchAndAiLoading'
import { SearchAndAiQuery } from 'products/web_analytics/frontend/searchAndAi/SearchAndAiQuery'
import { SearchAndAiTable } from 'products/web_analytics/frontend/searchAndAi/SearchAndAiTable'
import { SearchAndAiTrendHeader } from 'products/web_analytics/frontend/searchAndAi/SearchAndAiTrendHeader'

import { TileId } from './common'
import { PagePerformanceBreakdownModal } from './PagePerformanceBreakdownModal'
import { PagePerformanceCard } from './PagePerformanceCard'
import { PagePerformanceCardHeader } from './PagePerformanceCardHeader'
import { PagePerformanceEmptyState } from './PagePerformanceEmptyState'
import {
    PagePerformanceCrawlerState,
    PagePerformanceTabState,
    createPagePerformanceInsightProps,
    pagePerformanceLogic,
} from './pagePerformanceLogic'
import { PagePerformanceMetricCard } from './PagePerformanceMetricCard'
import { WebQuery, webAnalyticsDataTableQueryContext } from './tiles/WebAnalyticsTile'
import { webAnalyticsLogic } from './webAnalyticsLogic'

const CRAWLER_CAVEAT =
    "AI crawlers don't run JavaScript, so the browser SDK never sees them. Forward your server access logs to count them."

const SectionHeading = ({
    children,
    description,
}: {
    children: React.ReactNode
    description?: string
}): JSX.Element => (
    <div className="mb-4">
        <h2 className="mb-0 text-xl font-semibold text-primary">{children}</h2>
        {description ? <p className="m-0 text-sm text-secondary">{description}</p> : null}
    </div>
)

const SERVER_LOGS_DOCS = 'https://posthog.com/docs/web-analytics/sending-http-logs'

const CHANNEL_TYPE_DOCS = 'https://posthog.com/docs/data/channel-type'

const TabEmptyState = ({ state }: { state: PagePerformanceTabState }): JSX.Element =>
    state === 'no-events' ? (
        <PagePerformanceEmptyState
            title="Nothing to measure yet"
            action={
                <LemonButton
                    type="primary"
                    to={urls.onboarding({
                        productKey: ProductKey.WEB_ANALYTICS,
                        stepKey: OnboardingStepKey.INSTALL,
                    })}
                    data-attr="page-performance-onboarding"
                >
                    Open installation guide
                </LemonButton>
            }
        >
            <p className="m-0">
                Install PostHog on your site to see how search engines, AI assistants, and AI crawlers reach your pages.
            </p>
        </PagePerformanceEmptyState>
    ) : (
        <PagePerformanceEmptyState title="No pageviews in this date range">
            <p className="m-0">Pick a wider range to see how search and AI bring people to your pages.</p>
        </PagePerformanceEmptyState>
    )

const AiTrafficEmptyState = (): JSX.Element => (
    <PagePerformanceEmptyState
        title="No AI referrals in this range"
        action={
            <Link to={CHANNEL_TYPE_DOCS} target="_blank">
                How PostHog works out where a visit came from
            </Link>
        }
    >
        <p className="m-0">Nobody arrived from an AI assistant that PostHog could attribute.</p>
        <p className="m-0">
            This is a lower bound. Some assistants strip the referrer, and those visits land in Direct instead.
        </p>
    </PagePerformanceEmptyState>
)

const CrawlersEmptyState = ({ state }: { state: PagePerformanceCrawlerState }): JSX.Element =>
    state === 'needs-server-logs' ? (
        <PagePerformanceEmptyState
            title="PostHog can't see your AI crawlers yet"
            action={
                <LemonButton
                    type="primary"
                    to={SERVER_LOGS_DOCS}
                    targetBlank
                    data-attr="page-performance-server-logs-docs"
                >
                    Read the setup guide
                </LemonButton>
            }
        >
            <p className="m-0">
                Crawlers like GPTBot and ClaudeBot never run JavaScript, so the browser SDK never sees them. Forward
                your server or CDN access logs as <code>$http_log</code> events to count them here.
            </p>
            <p className="m-0">Already sending them? Try a wider date range.</p>
        </PagePerformanceEmptyState>
    ) : (
        <PagePerformanceEmptyState title="No AI crawlers in this range">
            <p className="m-0">
                Your server logs are reaching PostHog, but no AI crawler read these pages. Try a wider date range.
            </p>
        </PagePerformanceEmptyState>
    )

const AiTableCard = ({
    title,
    query,
    tileId,
}: {
    title: string
    query: DataTableNode
    tileId: TileId
}): JSX.Element => {
    const context = useMemo(
        (): QueryContext => ({
            ...webAnalyticsDataTableQueryContext,
            insightProps: createPagePerformanceInsightProps(tileId, 'table'),
            showLoadNextButton: true,
            tableLayout: 'fixed',
            suppressSlowQuerySuggestions: true,
        }),
        [tileId]
    )
    return (
        <PagePerformanceCard className="flex-1 min-w-0">
            <SearchAndAiQuery
                uniqueKey={`page-performance-${tileId}`}
                query={query}
                insightProps={context.insightProps!}
                context={context}
                header={<PagePerformanceCardHeader title={title} />}
            />
        </PagePerformanceCard>
    )
}

const AiTrendCard = ({
    title,
    query,
    tileId,
    uniqueKey,
}: {
    title: string
    query: InsightVizNode
    tileId: TileId
    uniqueKey: string
}): JSX.Element => (
    <div className="@min-[48rem]/search-ai:col-span-2 min-h-88 min-w-0 flex flex-col">
        <SearchAndAiQuery
            uniqueKey={uniqueKey}
            query={query}
            insightProps={createPagePerformanceInsightProps(tileId)}
            renderQuery={(insightProps) => (
                <WebQuery
                    attachTo={webAnalyticsLogic}
                    uniqueKey={uniqueKey}
                    query={query}
                    insightProps={insightProps}
                    tileId={tileId}
                    headerSlot={<SearchAndAiTrendHeader title={title} />}
                />
            )}
        />
    </div>
)

export const PagePerformance = (): JSX.Element => {
    useMountedLogic(pagePerformanceLogic)
    const {
        pageCandidates,
        candidatesError,
        candidatesLoading,
        overviewTotals,
        overviewMetrics,
        overviewError,
        overviewLoading,
        aiSectionQueries,
        dataState,
    } = useValues(pagePerformanceLogic)
    const { loadOverview, loadCandidates } = useActions(pagePerformanceLogic)
    const theme = useChartTheme()

    const feedbackBanner = (
        <LemonBanner
            type="info"
            dismissKey="web-analytics-search-and-ai-feedback-banner"
            action={{ children: 'Send feedback', id: 'web-analytics-search-and-ai-feedback-button' }}
        >
            We'd love to hear what you think about search and AI.
        </LemonBanner>
    )

    const overviewErrorBanner = overviewError && (
        <LemonBanner
            type="error"
            action={{ children: 'Try again', onClick: () => loadOverview(), loading: overviewLoading }}
        >
            {overviewTotals
                ? 'Could not update the summary metrics. Showing the previous results. Try again to refresh.'
                : 'Could not load the summary metrics. Try again to reload.'}
        </LemonBanner>
    )

    if (dataState.tab === 'no-events' || dataState.tab === 'no-traffic-in-range') {
        return (
            <div className="SearchAndAiDashboard @container/search-ai flex flex-col gap-5 min-w-0">
                {feedbackBanner}
                {overviewErrorBanner}
                <SearchAndAiLoading loading={overviewLoading}>
                    <TabEmptyState state={dataState.tab} />
                </SearchAndAiLoading>
            </div>
        )
    }

    return (
        <div className="SearchAndAiDashboard @container/search-ai flex flex-col gap-5 min-w-0">
            {feedbackBanner}
            <section>
                <SectionHeading>Key metrics</SectionHeading>
                {overviewErrorBanner}
                {(!overviewError || overviewTotals) && (
                    <SearchAndAiLoading loading={overviewLoading && !!overviewTotals}>
                        <div className="@container">
                            <div className="grid grid-cols-2 gap-3 @3xl:grid-cols-4">
                                {overviewMetrics.map(({ key, ...metric }, index) => (
                                    <PagePerformanceMetricCard
                                        key={key}
                                        {...metric}
                                        data-attr={`page-performance-metric-${key}`}
                                        color={seriesColor(theme, index)}
                                        theme={theme}
                                        loading={!overviewTotals && !overviewError}
                                        caveat={
                                            key === 'agent_crawls' && dataState.crawlers === 'needs-server-logs'
                                                ? CRAWLER_CAVEAT
                                                : undefined
                                        }
                                    />
                                ))}
                            </div>
                        </div>
                    </SearchAndAiLoading>
                )}
            </section>
            <section>
                <SectionHeading description="How each page earns its traffic, from search engines through to AI crawlers.">
                    Pages
                </SectionHeading>
                <PagePerformanceCard>
                    {candidatesError && (
                        <LemonBanner
                            type="error"
                            className="m-3"
                            action={{
                                children: 'Try again',
                                onClick: () => loadCandidates(),
                                loading: candidatesLoading,
                            }}
                        >
                            {pageCandidates
                                ? 'Could not update the page list. Showing the previous results. Try again to refresh.'
                                : 'Could not load the page list. Try again to reload.'}
                        </LemonBanner>
                    )}

                    {pageCandidates === null ? (
                        !candidatesError && <SearchAndAiLoading loading label="Loading pages" className="min-h-64" />
                    ) : (
                        <SearchAndAiTable />
                    )}
                </PagePerformanceCard>
            </section>
            <section>
                <SectionHeading description="People who landed on your site from an AI assistant such as ChatGPT, Claude, or Perplexity.">
                    Traffic from AI
                </SectionHeading>

                {dataState.aiTraffic === 'empty' ? (
                    <SearchAndAiLoading loading={overviewLoading}>
                        <AiTrafficEmptyState />
                    </SearchAndAiLoading>
                ) : (
                    <div className="grid grid-cols-1 @min-[48rem]/search-ai:grid-cols-2 gap-4">
                        <AiTrendCard
                            title="Referrals over time"
                            query={aiSectionQueries.referralTrend}
                            tileId={TileId.AI_REFERRALS_TREND}
                            uniqueKey="page-performance-ai-referrals-trend"
                        />
                        <AiTableCard
                            title="By engine"
                            query={aiSectionQueries.byEngine}
                            tileId={TileId.AI_REFERRALS_BY_ENGINE}
                        />
                        <AiTableCard
                            title="Landing pages from AI"
                            query={aiSectionQueries.landingPages}
                            tileId={TileId.AI_LANDING_PAGES}
                        />
                    </div>
                )}
            </section>
            <section>
                <SectionHeading description="Bots that read your pages to train a model or to answer someone's question about you.">
                    AI crawlers
                </SectionHeading>

                {dataState.crawlers === 'empty' || dataState.crawlers === 'needs-server-logs' ? (
                    <SearchAndAiLoading loading={overviewLoading}>
                        <CrawlersEmptyState state={dataState.crawlers} />
                    </SearchAndAiLoading>
                ) : (
                    <div className="grid grid-cols-1 @min-[48rem]/search-ai:grid-cols-2 gap-4">
                        <AiTrendCard
                            title="Crawler activity over time"
                            query={aiSectionQueries.crawlerTrend}
                            tileId={TileId.AI_CRAWLERS_TREND}
                            uniqueKey="page-performance-ai-crawler-trend"
                        />
                        <AiTableCard
                            title="By crawler"
                            query={aiSectionQueries.byCrawler}
                            tileId={TileId.AI_CRAWLERS}
                        />
                        <AiTableCard
                            title="Pages they read"
                            query={aiSectionQueries.crawledPages}
                            tileId={TileId.AI_CRAWLED_PAGES}
                        />
                    </div>
                )}
            </section>
            <PagePerformanceBreakdownModal />
        </div>
    )
}
