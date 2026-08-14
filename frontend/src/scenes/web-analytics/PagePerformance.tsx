import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'
import { useMemo } from 'react'

import { IconTrending } from '@posthog/icons'
import { LemonBanner, LemonButton, Spinner, Tooltip } from '@posthog/lemon-ui'

import { getColorVar } from 'lib/colors'
import { IconTrendingDown, IconTrendingFlat } from 'lib/lemon-ui/icons'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { percentage } from 'lib/utils/numbers'
import { tryDecodeURIComponent } from 'lib/utils/url'

import { OverviewGrid } from '~/queries/nodes/OverviewGrid/OverviewGrid'
import { Query } from '~/queries/Query/Query'
import { DataTableNode } from '~/queries/schema/schema-general'
import { QueryContext, QueryContextColumnComponent, QueryContextColumnTitleComponent } from '~/queries/types'

import { TileId } from './common'
import { PagePerformanceBreakdownModal } from './PagePerformanceBreakdownModal'
import {
    OVERVIEW_CARD_LABELS,
    PagePerformanceMetric,
    createPagePerformanceInsightProps,
    pagePerformanceLogic,
} from './pagePerformanceLogic'
import { WebQuery, webAnalyticsDataTableQueryContext } from './tiles/WebAnalyticsTile'
import { webAnalyticsLogic } from './webAnalyticsLogic'

const asTuple = (value: unknown): [number, number] | null => {
    if (Array.isArray(value) && value.length >= 2) {
        return [Number(value[0] ?? 0), Number(value[1] ?? 0)]
    }
    return null
}

const formatCount = (value: unknown): string =>
    typeof value === 'number' ? value.toLocaleString() : String(value ?? 0)

type TrendIndicator = {
    Icon: typeof IconTrending | typeof IconTrendingDown | typeof IconTrendingFlat
    color: string
    className: string
}

const trendIndicator = (pctChange: number | null): TrendIndicator | null => {
    if (pctChange === null) {
        return null
    }
    if (pctChange === 0) {
        return { Icon: IconTrendingFlat, color: getColorVar('muted'), className: 'text-secondary' }
    }
    if (pctChange > 0) {
        return { Icon: IconTrending, color: getColorVar('success'), className: 'text-success' }
    }
    return { Icon: IconTrendingDown, color: getColorVar('danger'), className: 'text-danger' }
}

const DeltaValue = ({ value }: { value: unknown }): JSX.Element => {
    const { compareFilter } = useValues(pagePerformanceLogic)
    const tuple = asTuple(value)
    if (!tuple) {
        return <span>{formatCount(value)}</span>
    }
    const [current, previous] = tuple
    const compareOn = compareFilter.compare !== false
    const pctChange = !compareOn || previous === 0 ? null : current === previous ? 0 : current / previous - 1
    const trend = trendIndicator(pctChange)
    const tooltip =
        pctChange !== null && pctChange !== 0
            ? `${current >= previous ? 'Increased' : 'Decreased'} by ${percentage(Math.abs(pctChange), 0)} vs previous period`
            : undefined
    return (
        <Tooltip title={tooltip}>
            <span className="whitespace-nowrap">
                {formatCount(current)}
                {trend && (
                    <span className={clsx('ml-1 inline-flex items-center text-xs', trend.className)}>
                        <trend.Icon color={trend.color} />
                        {pctChange !== null && pctChange !== 0 ? percentage(Math.abs(pctChange), 0) : ''}
                    </span>
                )}
            </span>
        </Tooltip>
    )
}

const ValueWithSubtitle = ({ value, subtitle }: { value: string; subtitle: string }): JSX.Element => (
    <div className="flex flex-col items-end leading-tight">
        <span className="whitespace-nowrap">{value}</span>
        <span className="text-secondary text-xs whitespace-nowrap">{subtitle}</span>
    </div>
)

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
            className="underline decoration-dotted underline-offset-2 hover:decoration-solid"
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

const VisitorsCell: QueryContextColumnComponent = ({ value }) => <DeltaValue value={value} />

const GoogleSearchCell: QueryContextColumnComponent = ({ value, record }) => {
    const tuple = asTuple(value)
    const google = tuple?.[0] ?? 0
    const visitors = tuple?.[1] ?? 0
    const share = visitors > 0 ? percentage(google / visitors, 0) : '-'
    return (
        <BreakdownLink metric="google_search" record={record}>
            <ValueWithSubtitle value={formatCount(google)} subtitle={`${share} of visitors`} />
        </BreakdownLink>
    )
}

const LlmReferralsCell: QueryContextColumnComponent = ({ value, record }) => (
    <BreakdownLink metric="llm_referrals" record={record}>
        <DeltaValue value={value} />
    </BreakdownLink>
)

const AgentCrawlsCell: QueryContextColumnComponent = ({ value, record }) => {
    const tuple = asTuple(value)
    const crawls = tuple?.[0] ?? 0
    const agents = tuple?.[1] ?? 0
    return (
        <BreakdownLink metric="agent_crawls" record={record}>
            <ValueWithSubtitle
                value={formatCount(crawls)}
                subtitle={`${agents} ${agents === 1 ? 'agent' : 'agents'}`}
            />
        </BreakdownLink>
    )
}

const ConversionsCell: QueryContextColumnComponent = ({ value }) => {
    const { conversionGoal } = useValues(pagePerformanceLogic)
    if (!conversionGoal) {
        return <span className="text-secondary">-</span>
    }
    const tuple = asTuple(value)
    const conversions = tuple?.[0] ?? 0
    const visitors = tuple?.[1] ?? 0
    const cvr = visitors > 0 ? percentage(conversions / visitors, 1) : '-'
    return <ValueWithSubtitle value={formatCount(conversions)} subtitle={`${cvr} CVR`} />
}

const AvgTimeCell: QueryContextColumnComponent = ({ value }) => (
    <span className="whitespace-nowrap">{value ? humanFriendlyDuration(Number(value)) : '-'}</span>
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
                className="group cursor-pointer inline-flex items-center"
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

const cardHeading = (title: string): JSX.Element => (
    <div className="flex items-baseline gap-2 px-3 pt-3">
        <h3 className="font-semibold m-0">{title}</h3>
    </div>
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
        <div className="border rounded bg-surface-primary flex flex-col flex-1">
            {cardHeading(title)}
            <Query uniqueKey={`page-performance-${tileId}`} query={query} readOnly context={context} />
        </div>
    )
}

export const PagePerformance = (): JSX.Element => {
    useMountedLogic(pagePerformanceLogic)
    const {
        pageTableQuery,
        pageCandidates,
        candidatesError,
        candidatesLoading,
        overviewCards,
        overviewError,
        overviewLoading,
        footerText,
        aiSectionQueries,
    } = useValues(pagePerformanceLogic)
    const { loadOverview, loadCandidates } = useActions(pagePerformanceLogic)

    const context = useMemo(
        (): QueryContext => ({
            insightProps: createPagePerformanceInsightProps(TileId.PAGE_PERFORMANCE_TABLE, 'table'),
            columns: {
                breakdown_value: { title: 'Page', render: PageCell, width: '28%' },
                visitors: { renderTitle: sortableTitle('Visitors', 'visitors'), render: VisitorsCell, align: 'right' },
                google_search: {
                    renderTitle: sortableTitle('Google search', 'google_search'),
                    render: GoogleSearchCell,
                    align: 'right',
                },
                llm_referrals: {
                    renderTitle: sortableTitle('LLM referrals', 'llm_referrals'),
                    render: LlmReferralsCell,
                    align: 'right',
                },
                agent_crawls: {
                    renderTitle: sortableTitle('Agent crawls', 'agent_crawls'),
                    render: AgentCrawlsCell,
                    align: 'right',
                },
                conversions: {
                    renderTitle: sortableTitle('Conversions', 'conversions'),
                    render: ConversionsCell,
                    align: 'right',
                },
                avg_time: {
                    renderTitle: sortableTitle('Avg. time', 'avg_time'),
                    render: AvgTimeCell,
                    align: 'right',
                },
            },
        }),
        []
    )

    return (
        <>
            <LemonBanner type="info" dismissKey="page-performance-alpha-info" className="mb-4">
                One leaderboard for how each page earns visits from Google, AI assistants, and the agents crawling your
                site. AI referrals are a lower bound: some assistants strip the referrer, so those visits land in
                Direct.
            </LemonBanner>
            {overviewError ? (
                <LemonBanner type="error" className="mb-4" action={{ children: 'Try again', onClick: loadOverview }}>
                    Could not load the summary metrics. Try again to reload.
                </LemonBanner>
            ) : (
                <OverviewGrid
                    items={overviewCards}
                    loading={overviewLoading && overviewCards.length === 0}
                    numSkeletons={4}
                    labelFromKey={(key) => OVERVIEW_CARD_LABELS[key] ?? key}
                />
            )}
            <div className="border rounded bg-surface-primary flex flex-col mt-4">
                <div className="flex items-baseline justify-between gap-2 px-3 pt-3">
                    <h3 className="font-semibold m-0">Pages ranked by visitors</h3>
                </div>
                {candidatesError ? (
                    <LemonBanner
                        type="error"
                        className="m-3"
                        action={{ children: 'Try again', onClick: loadCandidates }}
                    >
                        Could not load page performance. Try again to reload the leaderboard.
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
                <div className="text-secondary text-xs px-3 pb-3">{footerText}</div>
            </div>
            <div className="mt-4">
                <h2 className="text-lg font-semibold mb-4">Traffic from AI</h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="md:col-span-2 min-h-[350px] flex flex-col">
                        <WebQuery
                            attachTo={webAnalyticsLogic}
                            uniqueKey="page-performance-ai-referrals-trend"
                            query={aiSectionQueries.referralTrend}
                            insightProps={createPagePerformanceInsightProps(TileId.AI_REFERRALS_TREND)}
                            showIntervalSelect
                            tileId={TileId.AI_REFERRALS_TREND}
                            headerSlot={cardHeading('Referrals over time')}
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
            </div>
            <div className="mt-4">
                <h2 className="text-lg font-semibold mb-4">AI crawlers</h2>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="md:col-span-2 min-h-[350px] flex flex-col">
                        <WebQuery
                            attachTo={webAnalyticsLogic}
                            uniqueKey="page-performance-ai-crawler-trend"
                            query={aiSectionQueries.crawlerTrend}
                            insightProps={createPagePerformanceInsightProps(TileId.AI_CRAWLERS_TREND)}
                            showIntervalSelect
                            tileId={TileId.AI_CRAWLERS_TREND}
                            headerSlot={cardHeading('Crawler activity over time')}
                        />
                    </div>
                    <AiTableCard title="By crawler" query={aiSectionQueries.byCrawler} tileId={TileId.AI_CRAWLERS} />
                    <AiTableCard
                        title="Pages they read"
                        query={aiSectionQueries.crawledPages}
                        tileId={TileId.AI_CRAWLED_PAGES}
                    />
                </div>
            </div>
            <PagePerformanceBreakdownModal />
        </>
    )
}
