import { useActions } from 'kea'
import { useEffect } from 'react'

import { IconPullRequest } from '@posthog/icons'
import {
    Badge,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemSeparator,
    ItemTitle,
    Text,
    cn,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'

import type { TodayReportPreview } from '~/layout/today/todayPreviewCards'

import { selectReportCardImpactMetric } from 'products/signals/frontend/inbox/components/cards/ReportCardImpactMetric'
import {
    asReportMetricAggregateQuery,
    asReportMetricSeriesQuery,
} from 'products/signals/frontend/inbox/utils/reportMetrics'
import { pullRequestStateMeta } from 'products/tasks/frontend/spaces/TaskPullRequestChip'

import { todayLogic } from './todayLogic'
import { TodayReportHoverCardMetric } from './TodayReportHoverCardMetric'

/**
 * A report's hover card, on its left-bar row and on its links in the briefing text: its priority, why the
 * briefing picked it, what happened to it since, its implementation pull request, summary and headline
 * metric. The text comes with the page. The metric runs its live query while the card is open, and a
 * report without a metric shows the card without it.
 */
export function TodayReportHoverCard({ preview }: { preview: TodayReportPreview }): JSX.Element {
    const { card } = preview
    const { reportPreviewed } = useActions(todayLogic)
    // Keyed on the report, not the card object: a poll replaces the object while the card stays open.
    useEffect(() => {
        reportPreviewed(card.key, preview.surface)
    }, [card.key, preview.surface, reportPreviewed])

    const pullRequestState = pullRequestStateMeta(card.pullRequestState)
    const metric = selectReportCardImpactMetric(card.metrics)
    const aggregateQuery = metric ? asReportMetricAggregateQuery(metric.query) : null
    const seriesQuery = metric ? asReportMetricSeriesQuery(metric) : null
    const lead = [card.priority, card.reason].filter(Boolean).join(' · ')
    const hasChart = !!(metric && aggregateQuery && seriesQuery)
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
                            {lead && <span>{lead}</span>}
                            {card.pullRequestUrl && (
                                <span className="flex min-w-0 items-center gap-1.5">
                                    {lead && <span aria-hidden>·</span>}
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
                    {card.summary && (
                        // A few lines say what the report is about without turning the card into the report.
                        // Without a chart below, the summary gets the room.
                        <Text
                            size="xs"
                            variant="muted"
                            className={cn('mt-1 leading-snug break-words', hasChart ? 'line-clamp-2' : 'line-clamp-5')}
                        >
                            {card.summary}
                        </Text>
                    )}
                </ItemContent>
                {card.stateLabel && (
                    <ItemActions className="self-start">
                        <Badge variant={card.resolved ? 'completed' : 'default'}>{card.stateLabel}</Badge>
                    </ItemActions>
                )}
            </Item>
            {metric && aggregateQuery && seriesQuery && (
                <>
                    <ItemSeparator className="my-0" />
                    <Item size="xs">
                        <ItemContent className="min-w-0">
                            <TodayReportHoverCardMetric
                                cardKey={card.key}
                                metric={metric}
                                aggregateQuery={aggregateQuery.source}
                                seriesQuery={seriesQuery.source}
                            />
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
        </div>
    )
}
