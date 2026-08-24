import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'
import { forwardRef, useMemo } from 'react'

import { IconTrending } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { useChartTheme } from 'lib/charts/hooks'
import { seriesColor } from 'lib/charts/utils/theme'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { tryDecodeURIComponent } from 'lib/utils/url'

import { Query } from '~/queries/Query/Query'
import { DataTableNode } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumnComponent, QueryContextColumnTitleComponent } from '~/queries/types'

import { TileId } from './common'
import { PagePerformanceBreakdownModal } from './PagePerformanceBreakdownModal'
import { PagePerformanceCard } from './PagePerformanceCard'
import { PagePerformanceCardHeader } from './PagePerformanceCardHeader'
import {
    PagePerformanceMetric,
    changeVsPrevious,
    createPagePerformanceInsightProps,
    formatShare,
    pageVisitorsFromRecord,
    pagePerformanceLogic,
    parseMetricCell,
} from './pagePerformanceLogic'
import { PagePerformanceMetricCard } from './PagePerformanceMetricCard'
import { WebQuery, webAnalyticsDataTableQueryContext } from './tiles/WebAnalyticsTile'
import { webAnalyticsLogic } from './webAnalyticsLogic'

const formatCount = (value: unknown): string =>
    typeof value === 'number' ? value.toLocaleString() : String(value ?? 0)

type TrendIndicator = {
    Icon: typeof IconTrending | typeof IconTrendingDown | typeof IconTrendingFlat
    className: string
}

// The icons fill with `currentColor`, so the wrapper's text color is the whole story.
const trendIndicator = (pctChange: number): TrendIndicator => {
    if (pctChange === 0) {
        return { Icon: IconTrendingFlat, className: 'text-secondary' }
    }
    if (pctChange > 0) {
        return { Icon: IconTrending, className: 'text-success' }
    }
    return { Icon: IconTrendingDown, className: 'text-danger' }
}

interface CellValueProps extends React.HTMLAttributes<HTMLDivElement> {
    value: string
    secondary?: React.ReactNode
}

/** Every numeric cell is one shape: the value, centered over a muted second line giving its context.
 *  Forwards its ref and props so `Tooltip` can use it as a trigger. */
const CellValue = forwardRef<HTMLDivElement, CellValueProps>(function CellValue(
    { value, secondary, ...rest },
    ref
): JSX.Element {
    return (
        <div ref={ref} className="flex flex-col items-center leading-tight" {...rest}>
            <span className="whitespace-nowrap">{value}</span>
            {secondary ? <span className="text-xs whitespace-nowrap text-secondary">{secondary}</span> : null}
        </div>
    )
})

/** The muted line under every value: its share of visitors, then how it moved. */
const secondaryLine = (share: string | null, pctChange: number | null): React.ReactNode | undefined => {
    if (!share && pctChange === null) {
        return null
    }
    const trend = pctChange === null ? null : trendIndicator(pctChange)
    return (
        <span className="inline-flex items-center gap-1">
            {share}
            {share && trend ? <span>·</span> : null}
            {trend && pctChange !== null ? (
                <span className={clsx('inline-flex items-center', trend.className)}>
                    <trend.Icon />
                    {percentage(Math.abs(pctChange), 0)}
                </span>
            ) : null}
        </span>
    )
}

const changeTooltip = (pctChange: number | null): string | null =>
    pctChange
        ? `${pctChange > 0 ? 'Increased' : 'Decreased'} by ${percentage(Math.abs(pctChange), 0)} vs previous period`
        : null

/** The shared body of every metric column: a count over its share of some whole and its movement. */
const MetricCell = ({
    current,
    previous,
    whole,
    tooltip,
}: {
    current: number
    previous: number
    whole: number
    tooltip: string
}): JSX.Element => {
    const { comparePeriods } = useValues(pagePerformanceLogic)
    const pctChange = comparePeriods ? changeVsPrevious(current, previous) : null
    return (
        <Tooltip title={[tooltip, changeTooltip(pctChange)].filter(Boolean).join('. ')}>
            <CellValue value={formatCount(current)} secondary={secondaryLine(formatShare(current, whole), pctChange)} />
        </Tooltip>
    )
}

const BreakdownLink = ({
    metric,
    record,
    children,
}: {
    metric: PagePerformanceMetric
    record: unknown
    children: React.ReactNode
}): JSX.Element => {
    const { openBreakdown } = useActions(pagePerformanceLogic)
    const page = Array.isArray(record) ? String(record[0] ?? '') : ''
    return (
        <LemonButton
            type="tertiary"
            size="small"
            noPadding
            fullWidth
            center
            className="hover:underline"
            onClick={() => openBreakdown({ page, metric })}
        >
            {children}
        </LemonButton>
    )
}

const PageCell: QueryContextColumnComponent = ({ value }) => {
    if (typeof value !== 'string') {
        return <span className="text-secondary italic">(none)</span>
    }
    const decoded = tryDecodeURIComponent(value)
    return (
        <Tooltip title={decoded}>
            <span className="font-medium">{decoded}</span>
        </Tooltip>
    )
}

const VisitorsCell: QueryContextColumnComponent = ({ value }) => {
    const { siteVisitors } = useValues(pagePerformanceLogic)
    const cell = parseMetricCell(value)
    if (!cell) {
        return <span>{formatCount(value)}</span>
    }
    const share = formatShare(cell.current, siteVisitors)
    return (
        <MetricCell
            current={cell.current}
            previous={cell.previous}
            whole={siteVisitors}
            tooltip={share ? `${share} of the ${formatCount(siteVisitors)} visitors to your site this period` : ''}
        />
    )
}

const GoogleSearchCell: QueryContextColumnComponent = ({ value, record }) => {
    const cell = parseMetricCell(value)
    const visitors = pageVisitorsFromRecord(record)
    return (
        <BreakdownLink metric="google_search" record={record}>
            <MetricCell
                current={cell?.current ?? 0}
                previous={cell?.previous ?? 0}
                whole={visitors}
                tooltip={`${formatCount(cell?.current ?? 0)} of this page's ${formatCount(visitors)} visitors came from Google search`}
            />
        </BreakdownLink>
    )
}

const LlmReferralsCell: QueryContextColumnComponent = ({ value, record }) => {
    const cell = parseMetricCell(value)
    const visitors = pageVisitorsFromRecord(record)
    return (
        <BreakdownLink metric="llm_referrals" record={record}>
            <MetricCell
                current={cell?.current ?? 0}
                previous={cell?.previous ?? 0}
                whole={visitors}
                tooltip={`${formatCount(cell?.current ?? 0)} of this page's ${formatCount(visitors)} visitors arrived from an AI assistant. This is a lower bound: some assistants strip the referrer, so those visits land in Direct`}
            />
        </BreakdownLink>
    )
}

// Crawls count every bot hit rather than unique people, so this column shows a bot count, not a share.
const AgentCrawlsCell: QueryContextColumnComponent = ({ value, record }) => {
    const cell = parseMetricCell(value)
    const crawls = cell?.current ?? 0
    const agents = pluralize(cell?.previous ?? 0, 'agent')
    const visitors = pageVisitorsFromRecord(record)
    return (
        <BreakdownLink metric="agent_crawls" record={record}>
            <Tooltip
                title={`${formatCount(crawls)} crawls of this page by ${agents}, against ${formatCount(visitors)} human visitors. Crawls count every bot hit, so they are not a share of visitors`}
            >
                <CellValue value={formatCount(crawls)} secondary={crawls > 0 ? agents : undefined} />
            </Tooltip>
        </BreakdownLink>
    )
}

const ConversionsCell: QueryContextColumnComponent = ({ value, record }) => {
    const { conversionGoal } = useValues(pagePerformanceLogic)
    const cell = parseMetricCell(value)
    const visitors = pageVisitorsFromRecord(record)
    if (!conversionGoal) {
        return <span className="text-secondary">-</span>
    }
    return (
        <MetricCell
            current={cell?.current ?? 0}
            previous={cell?.previous ?? 0}
            whole={visitors}
            tooltip={`${formatCount(cell?.current ?? 0)} conversions from this page's ${formatCount(visitors)} visitors`}
        />
    )
}

const AvgTimeCell: QueryContextColumnComponent = ({ value }) => (
    <Tooltip
        title={
            value
                ? 'The 90th percentile time visitors spent on this page before moving on. Needs a following pageview to measure, so the last page of a visit is not counted'
                : 'No timing yet. This needs a following pageview to measure against, so pages that end a visit stay blank'
        }
    >
        <span className="whitespace-nowrap">{value ? humanFriendlyDuration(Number(value)) : '-'}</span>
    </Tooltip>
)

const sortableTitle = (label: string, column: string): QueryContextColumnTitleComponent =>
    function SortableTitle() {
        const { orderBy } = useValues(pagePerformanceLogic)
        const { setOrderBy } = useActions(pagePerformanceLogic)
        const active = orderBy.column === column
        const ascending = active && orderBy.direction === 'ASC'
        return (
            <LemonButton
                type="tertiary"
                size="small"
                noPadding
                // `uppercase` because a <button> doesn't inherit the thead text-transform, so without
                // it the sortable headers read sentence case next to the plain ones.
                className="group cursor-pointer inline-flex items-center uppercase"
                onClick={() => setOrderBy(column, active && orderBy.direction === 'DESC' ? 'ASC' : 'DESC')}
                aria-label={`Sort by ${label} ${active && orderBy.direction === 'DESC' ? 'ascending' : 'descending'}`}
            >
                {label}
                <IconTrending
                    className={clsx('ml-1 opacity-0 group-hover:opacity-100', {
                        'text-primary opacity-100': active,
                        'rotate-180': ascending,
                    })}
                />
            </LemonButton>
        )
    }

const SectionHeading = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <h2 className="mb-4 text-xl font-semibold text-primary">{children}</h2>
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
        }),
        [tileId]
    )
    return (
        <PagePerformanceCard title={title} className="flex-1">
            <Query uniqueKey={`page-performance-${tileId}`} query={query} readOnly context={context} />
        </PagePerformanceCard>
    )
}

export const PagePerformance = (): JSX.Element => {
    useMountedLogic(pagePerformanceLogic)
    const {
        pageTableQuery,
        pageCandidates,
        candidatesError,
        candidatesLoading,
        overviewMetrics,
        overviewError,
        overviewLoading,
        footerText,
        aiSectionQueries,
    } = useValues(pagePerformanceLogic)
    const { loadOverview, loadCandidates } = useActions(pagePerformanceLogic)
    const theme = useChartTheme()

    const context = useMemo(
        (): QueryContext => ({
            insightProps: createPagePerformanceInsightProps(TileId.PAGE_PERFORMANCE_TABLE, 'table'),
            columns: {
                breakdown_value: { title: 'Page', render: PageCell, width: '28%' },
                visitors: { renderTitle: sortableTitle('Visitors', 'visitors'), render: VisitorsCell, align: 'center' },
                google_search: {
                    renderTitle: sortableTitle('Google search', 'google_search'),
                    render: GoogleSearchCell,
                    align: 'center',
                },
                llm_referrals: {
                    renderTitle: sortableTitle('LLM referrals', 'llm_referrals'),
                    render: LlmReferralsCell,
                    align: 'center',
                },
                agent_crawls: {
                    renderTitle: sortableTitle('Agent crawls', 'agent_crawls'),
                    render: AgentCrawlsCell,
                    align: 'center',
                },
                conversions: {
                    renderTitle: sortableTitle('Conversions', 'conversions'),
                    render: ConversionsCell,
                    align: 'center',
                },
                avg_time: {
                    renderTitle: sortableTitle('Avg. time', 'avg_time'),
                    render: AvgTimeCell,
                    align: 'center',
                },
            },
        }),
        []
    )

    return (
        <div className="flex flex-col gap-4">
            <LemonBanner
                type="info"
                dismissKey="web-analytics-search-and-ai-feedback-banner"
                action={{ children: 'Send feedback', id: 'web-analytics-search-and-ai-feedback-button' }}
            >
                We'd love to hear what you think about search and AI.
            </LemonBanner>
            <section>
                <SectionHeading>Key metrics</SectionHeading>
                {overviewError ? (
                    <LemonBanner
                        type="error"
                        action={{ children: 'Try again', onClick: loadOverview, loading: overviewLoading }}
                    >
                        Could not load the summary metrics. Try again to reload.
                    </LemonBanner>
                ) : (
                    <div className="@container">
                        <div className="grid grid-cols-2 gap-3 @3xl:grid-cols-4">
                            {overviewMetrics.map(({ key, ...metric }, index) => (
                                <PagePerformanceMetricCard
                                    key={key}
                                    {...metric}
                                    data-attr={`page-performance-metric-${key}`}
                                    color={seriesColor(theme, index)}
                                    theme={theme}
                                    loading={overviewLoading}
                                />
                            ))}
                        </div>
                    </div>
                )}
            </section>
            <section>
                <SectionHeading>Pages</SectionHeading>
                <PagePerformanceCard footer={footerText}>
                    {candidatesError ? (
                        <LemonBanner
                            type="error"
                            className="m-3"
                            action={{ children: 'Try again', onClick: loadCandidates, loading: candidatesLoading }}
                        >
                            Could not load the page leaderboard. Try again to reload it.
                        </LemonBanner>
                    ) : candidatesLoading && pageCandidates === null ? (
                        <div className="flex items-center justify-center py-12">
                            <Spinner className="text-2xl" />
                        </div>
                    ) : (
                        <Query
                            uniqueKey="page-performance-table"
                            query={pageTableQuery}
                            readOnly
                            context={context}
                            dataAttr="page-performance-table"
                        />
                    )}
                </PagePerformanceCard>
            </section>
            <section>
                <SectionHeading>Traffic from AI</SectionHeading>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="md:col-span-2 min-h-[350px] flex flex-col">
                        <WebQuery
                            attachTo={webAnalyticsLogic}
                            uniqueKey="page-performance-ai-referrals-trend"
                            query={aiSectionQueries.referralTrend}
                            insightProps={createPagePerformanceInsightProps(TileId.AI_REFERRALS_TREND)}
                            showIntervalSelect
                            tileId={TileId.AI_REFERRALS_TREND}
                            headerSlot={<PagePerformanceCardHeader title="Referrals over time" />}
                        />
                    </div>
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
            </section>
            <section>
                <SectionHeading>AI crawlers</SectionHeading>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="md:col-span-2 min-h-[350px] flex flex-col">
                        <WebQuery
                            attachTo={webAnalyticsLogic}
                            uniqueKey="page-performance-ai-crawler-trend"
                            query={aiSectionQueries.crawlerTrend}
                            insightProps={createPagePerformanceInsightProps(TileId.AI_CRAWLERS_TREND)}
                            showIntervalSelect
                            tileId={TileId.AI_CRAWLERS_TREND}
                            headerSlot={<PagePerformanceCardHeader title="Crawler activity over time" />}
                        />
                    </div>
                    <AiTableCard title="By crawler" query={aiSectionQueries.byCrawler} tileId={TileId.AI_CRAWLERS} />
                    <AiTableCard
                        title="Pages they read"
                        query={aiSectionQueries.crawledPages}
                        tileId={TileId.AI_CRAWLED_PAGES}
                    />
                </div>
            </section>
            <PagePerformanceBreakdownModal />
        </div>
    )
}
