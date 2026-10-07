import { useActions, useValues } from 'kea'
import { Suspense, useEffect } from 'react'

import { IconCheckCircle, IconHide, IconLeave, IconPullRequest } from '@posthog/icons'
import {
    Badge,
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemSeparator,
    ItemTitle,
    Skeleton,
    Text,
    cn,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { lazyWithRetry } from 'lib/utils/retryImport'
import { pluralize } from 'lib/utils/strings'

import type { TodayReportPreview } from '~/layout/today/todayPreviewCards'

import { reportChartGraphQuery } from 'products/signals/frontend/inbox/utils/reportChartQuery'
import {
    asReportMetricAggregateQuery,
    asReportMetricSeriesQuery,
    reportMetricRowParts,
    selectReportCardImpactMetric,
} from 'products/signals/frontend/inbox/utils/reportMetrics'
import { pullRequestStateMeta } from 'products/tasks/frontend/spaces/TaskPullRequestChip'

import { overrideStateLabel } from './todayBriefingItems'
import { TodayReportVerdict, todayLogic } from './todayLogic'
import { isSampleReportId } from './todaySampleReports'

// The charts load on the first hover: the card sits in the app shell, and the query and chart code
// they need must stay out of the bundle every page loads.
const TodayReportHoverCardMetric = lazyWithRetry(() =>
    import('./TodayReportHoverCardMetric').then((m) => ({ default: m.TodayReportHoverCardMetric }))
)
const TodayReportHoverCardChart = lazyWithRetry(() =>
    import('./TodayReportHoverCardChart').then((m) => ({ default: m.TodayReportHoverCardChart }))
)

// The card lists a few more metrics by their saved value. A chart for each would run two live queries per metric on every hover.
const LISTED_METRIC_COUNT = 2

/**
 * A report's hover card, on its left-bar row and on its links in the briefing text: its priority, why the
 * briefing picked it, what happened to it since, its implementation pull request, summary and headline
 * metric. The text comes with the page. The metric runs its live query while the card is open, and a
 * report without a metric shows the card without it.
 */
export function TodayReportHoverCard({ preview }: { preview: TodayReportPreview }): JSX.Element {
    const { card } = preview
    const { reportStateOverrides } = useValues(todayLogic)
    const { reportPreviewed, requestReportVerdict, leaveReportReview } = useActions(todayLogic)
    // Keyed on the report, not the card object: a poll replaces the object while the card stays open.
    useEffect(() => {
        reportPreviewed(card.key, preview.surface)
    }, [card.key, preview.surface, reportPreviewed])

    // Read live, not from the card: the card stays open after a click, and keeps the payload it opened with.
    const override = card.reportId ? reportStateOverrides[card.reportId] : undefined
    const stateLabel = override ? overrideStateLabel(override) : card.stateLabel
    const resolved = override ? override === 'done' : card.resolved
    const { reportId } = card
    const giveVerdict = (verdict: TodayReportVerdict): void => {
        if (reportId) {
            requestReportVerdict(
                {
                    reportId,
                    title: card.title,
                    hasOpenPullRequest: card.pullRequestState === 'open' || card.pullRequestState === 'draft',
                },
                verdict,
                preview.surface
            )
        }
    }
    const isSample = !!reportId && isSampleReportId(reportId)
    const pullRequestState = pullRequestStateMeta(card.pullRequestState)
    const metric = selectReportCardImpactMetric(card.metrics)
    const aggregateQuery = metric ? asReportMetricAggregateQuery(metric.query) : null
    const seriesQuery = metric ? asReportMetricSeriesQuery(metric) : null
    const lead = [card.priority, card.reason].filter(Boolean).join(' · ')
    const hasMetricChart = !!(metric && aggregateQuery && seriesQuery)
    // A report without a metric to chart shows the first chart from its body instead.
    const bodyChart = hasMetricChart
        ? null
        : card.charts.map((chart) => ({ chart, query: reportChartGraphQuery(chart) })).find(({ query }) => query)
    const hasChart = hasMetricChart || !!bodyChart
    const otherMetrics = card.metrics.flatMap((candidate) => {
        const parts = hasMetricChart && candidate === metric ? null : reportMetricRowParts(candidate, candidate.value)
        return parts ? [{ metric: candidate, value: [parts.value, parts.unit].filter(Boolean).join(' ') }] : []
    })
    const listedMetrics = otherMetrics.slice(0, LISTED_METRIC_COUNT)
    const unlistedMetricCount = otherMetrics.length - listedMetrics.length
    const activity = [
        card.signalCount ? pluralize(card.signalCount, 'signal') : null,
        card.updatedAt ? `updated ${dayjs(card.updatedAt).fromNow()}` : null,
    ]
        .filter(Boolean)
        .join(' · ')

    return (
        <div className="flex flex-col" data-attr="today-report-hover-card">
            {/* `flex-nowrap` keeps the state badge beside a long title. */}
            <Item size="xs" className="flex-nowrap items-start">
                <ItemContent className="min-w-0 gap-0.5">
                    {/* `wrap-anywhere`: the title sizes to its content, so a long title would widen the card. */}
                    <ItemTitle className="wrap-anywhere">
                        <span className="min-w-0 font-semibold">{card.title}</span>
                    </ItemTitle>
                    {(lead || card.pullRequestUrl) && (
                        <ItemDescription className="flex flex-wrap items-center gap-x-1.5">
                            {/* The separator ends the lead rather than opening the link, so a wrap leaves it
                                trailing the first line instead of reading as a bullet on the second. */}
                            {lead && <span>{card.pullRequestUrl ? `${lead} ·` : lead}</span>}
                            {card.pullRequestUrl && (
                                <span className="flex min-w-0 items-center gap-1.5">
                                    <LinkPrimitive
                                        to={card.pullRequestUrl}
                                        target="_blank"
                                        data-attr="today-report-hover-card-pr"
                                        // Dotted at rest, so the one mark that opens something reads as a link.
                                        className="flex min-w-0 items-center gap-1 font-normal text-foreground underline decoration-dotted underline-offset-2"
                                    >
                                        <IconPullRequest
                                            className={cn('size-3 shrink-0', pullRequestState?.iconClassName)}
                                        />
                                        <span className="truncate">
                                            {pullRequestState
                                                ? `PR ${pullRequestState.label.toLowerCase()}`
                                                : 'Pull request'}
                                        </span>
                                    </LinkPrimitive>
                                </span>
                            )}
                        </ItemDescription>
                    )}
                </ItemContent>
                {stateLabel && (
                    <ItemActions className="self-start">
                        <Badge variant={resolved ? 'completed' : 'default'}>{stateLabel}</Badge>
                    </ItemActions>
                )}
            </Item>
            {card.summary && (
                // Its own row, so the summary uses the full card width, not the column beside the state badge.
                <Item size="xs" className="pt-0">
                    <ItemContent className="min-w-0">
                        {/* A few lines say what the report is about. Without a chart below, the summary gets the room. */}
                        <Text
                            size="xs"
                            variant="muted"
                            className={cn('leading-snug break-words', hasChart ? 'line-clamp-3' : 'line-clamp-8')}
                        >
                            {card.summary}
                        </Text>
                    </ItemContent>
                </Item>
            )}
            {(hasChart || listedMetrics.length > 0) && (
                <>
                    <ItemSeparator className="my-0" />
                    <Item size="xs">
                        <ItemContent className="min-w-0 gap-1.5">
                            {/* The metric and report charts are `h-36`, so the card keeps its size while they load. */}
                            <Suspense fallback={hasChart ? <Skeleton className="h-36 w-full" /> : null}>
                                {metric && aggregateQuery && seriesQuery && (
                                    <TodayReportHoverCardMetric
                                        cardKey={card.key}
                                        metric={metric}
                                        aggregateQuery={aggregateQuery.source}
                                        seriesQuery={seriesQuery.source}
                                    />
                                )}
                                {bodyChart?.query && (
                                    <TodayReportHoverCardChart
                                        cardKey={card.key}
                                        chart={bodyChart.chart}
                                        query={bodyChart.query}
                                    />
                                )}
                            </Suspense>
                            {listedMetrics.map(({ metric: listed, value }) => (
                                <div
                                    key={listed.metric_id}
                                    className="flex items-baseline justify-between gap-2"
                                    data-attr="today-report-hover-card-listed-metric"
                                >
                                    <Text
                                        size="xs"
                                        variant="muted"
                                        render={<span title={listed.title} />}
                                        className="truncate"
                                    >
                                        {listed.title}
                                    </Text>
                                    <Text
                                        size="xs"
                                        render={<span translate="no" />}
                                        className="shrink-0 font-semibold tabular-nums"
                                    >
                                        {value}
                                    </Text>
                                </div>
                            ))}
                            {unlistedMetricCount > 0 && (
                                <Text size="xs" variant="muted" render={<span />}>
                                    {`${pluralize(unlistedMetricCount, 'more metric')} in the report`}
                                </Text>
                            )}
                        </ItemContent>
                    </Item>
                </>
            )}
            <ItemSeparator className="my-0" />
            {/* Each half wraps as a whole, so a narrow card never leaves one word on its own line. */}
            <div className="flex flex-wrap justify-between gap-x-3 px-3 py-2">
                <Text size="xs" variant="muted" render={<span />} className="whitespace-nowrap">
                    {card.sourceLabel}
                </Text>
                {activity && (
                    <Text size="xs" variant="muted" render={<span />} className="whitespace-nowrap">
                        {activity}
                    </Text>
                )}
            </div>
            {reportId && !stateLabel && (
                <>
                    <ItemSeparator className="my-0" />
                    <div className="flex flex-wrap justify-between gap-1.5 px-3 py-2">
                        <Button
                            variant="outline"
                            size="xs"
                            disabled={isSample}
                            onClick={() => giveVerdict('resolve')}
                            data-attr="today-report-hover-card-resolve"
                        >
                            <IconCheckCircle />
                            Resolve
                        </Button>
                        {/* The click gives the report a state label, which takes this whole row off the
                            card, so the request cannot be sent twice and needs no in-flight state. */}
                        {card.canLeaveReview && (
                            <Button
                                variant="outline"
                                size="xs"
                                disabled={isSample}
                                title="Remove yourself from this report’s reviewers"
                                onClick={() => leaveReportReview(reportId, preview.surface)}
                                data-attr="today-report-hover-card-leave-review"
                            >
                                <IconLeave />
                                Not me
                            </Button>
                        )}
                        <Button
                            variant="outline"
                            size="xs"
                            disabled={isSample}
                            onClick={() => giveVerdict('dismiss')}
                            data-attr="today-report-hover-card-dismiss"
                        >
                            <IconHide />
                            Dismiss
                        </Button>
                    </div>
                </>
            )}
        </div>
    )
}
