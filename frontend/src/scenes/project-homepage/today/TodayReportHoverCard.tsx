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

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { TodayReportPreview } from '~/layout/today/todayPreviewCards'

import { selectReportCardImpactMetric } from 'products/signals/frontend/inbox/components/cards/ReportCardImpactMetric'
import {
    asReportMetricAggregateQuery,
    asReportMetricSeriesQuery,
} from 'products/signals/frontend/inbox/utils/reportMetrics'
import { pullRequestStateMeta } from 'products/tasks/frontend/spaces/TaskPullRequestChip'

import { itemReasonLabel, itemSource, itemStateLabel } from './todayBriefingItems'
import { todayLogic } from './todayLogic'
import { TodayReportHoverCardMetric } from './TodayReportHoverCardMetric'

/**
 * A report's hover card, on its left-bar row and on its links in the briefing text: its priority, why the
 * briefing picked it, what happened to it since, its implementation pull request, summary and headline
 * metric. The text comes with the briefing. The metric runs its live query while the card is open.
 */
export function TodayReportHoverCard({ preview }: { preview: TodayReportPreview }): JSX.Element {
    const { item } = preview
    const { reportPreviewed } = useActions(todayLogic)
    // Keyed on the report, not the item object: a poll replaces the object while the card stays open.
    useEffect(() => {
        reportPreviewed(item.key, preview.surface)
    }, [item.key, preview.surface, reportPreviewed])

    const stateLabel = itemStateLabel(item)
    const report = item.report
    const pullRequestState = pullRequestStateMeta(report?.pull_request_state)
    const metric = selectReportCardImpactMetric(report?.metrics)
    const aggregateQuery = metric ? asReportMetricAggregateQuery(metric.query) : null
    const seriesQuery = metric ? asReportMetricSeriesQuery(metric) : null

    return (
        <div className="flex flex-col" data-attr="today-report-hover-card">
            {/* `flex-nowrap` keeps the state badge beside a long title. */}
            <Item size="xs" className="flex-nowrap items-start">
                <ItemContent className="min-w-0 gap-0.5">
                    {/* `wrap-anywhere`: the title sizes to its content, so a long title would widen the card. */}
                    <ItemTitle className="wrap-anywhere">
                        <span className="min-w-0 font-semibold">{item.title}</span>
                    </ItemTitle>
                    <ItemDescription className="flex flex-wrap items-center gap-x-1.5">
                        <span>{[report?.priority, itemReasonLabel(item)].filter(Boolean).join(' · ')}</span>
                        {report?.pull_request_url && (
                            <span className="flex min-w-0 items-center gap-1.5">
                                <span aria-hidden>·</span>
                                <LinkPrimitive
                                    to={report.pull_request_url}
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
                    {report?.summary && (
                        // Two lines say what the report is about without turning the card into the report.
                        <Text size="xs" variant="muted" className="mt-1 line-clamp-2 leading-snug break-words">
                            {report.summary}
                        </Text>
                    )}
                </ItemContent>
                {stateLabel && (
                    <ItemActions className="self-start">
                        <Badge variant={item.state === 'done' ? 'completed' : 'default'}>{stateLabel}</Badge>
                    </ItemActions>
                )}
            </Item>
            {metric && aggregateQuery && seriesQuery && (
                <>
                    <ItemSeparator className="my-0" />
                    <Item size="xs">
                        <ItemContent className="min-w-0">
                            <TodayReportHoverCardMetric
                                itemKey={item.key}
                                metric={metric}
                                aggregateQuery={aggregateQuery.source}
                                seriesQuery={seriesQuery.source}
                            />
                        </ItemContent>
                    </Item>
                </>
            )}
            <ItemSeparator className="my-0" />
            <Text size="xs" variant="muted" render={<span />} className="px-3 py-2">
                {itemSource(item).label}
            </Text>
        </div>
    )
}
