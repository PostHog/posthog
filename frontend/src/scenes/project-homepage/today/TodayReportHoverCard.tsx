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
import { Sparkline } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { TodayHoverCardFact } from '~/layout/today/TodayHoverCardFact'
import type { TodayReportPreview } from '~/layout/today/todayPreviewCards'

import { selectReportCardImpactMetric } from 'products/signals/frontend/inbox/components/cards/ReportCardImpactMetric'
import { reportMetricChartType, reportMetricRowParts } from 'products/signals/frontend/inbox/utils/reportMetrics'
import { pullRequestStateMeta } from 'products/tasks/frontend/spaces/TaskPullRequestChip'

import { itemReasonLabel, itemSource, itemStateLabel } from './todayBriefingItems'
import { todayLogic } from './todayLogic'

/**
 * A report's hover card, on its left-bar row and on its links in the briefing text: why the briefing
 * picked it, what happened to it since, its priority, implementation pull request, summary and headline
 * metric. Everything comes with the briefing, so the card opens without a request.
 */
export function TodayReportHoverCard({ preview }: { preview: TodayReportPreview }): JSX.Element {
    const { item } = preview
    const { reportPreviewed } = useActions(todayLogic)
    const theme = useChartTheme()
    // Keyed on the report, not the item object: a poll replaces the object while the card stays open.
    useEffect(() => {
        reportPreviewed(item.key, preview.surface)
    }, [item.key, preview.surface, reportPreviewed])

    const stateLabel = itemStateLabel(item)
    const report = item.report
    const pullRequestState = pullRequestStateMeta(report?.pull_request_state)
    const metric = selectReportCardImpactMetric(report?.metrics)
    const metricParts = metric ? reportMetricRowParts(metric, metric.value) : null
    const series = metric?.series?.filter((point) => Number.isFinite(point)) ?? []

    return (
        <div className="flex flex-col" data-attr="today-report-hover-card">
            {/* `flex-nowrap` keeps the state badge beside a long title. */}
            <Item size="xs" className="flex-nowrap items-start">
                <ItemContent className="min-w-0">
                    {/* `wrap-anywhere`: the title sizes to its content, so a long title would widen the card. */}
                    <ItemTitle className="wrap-anywhere">
                        <span className="min-w-0 font-semibold">{item.title}</span>
                    </ItemTitle>
                    <ItemDescription>
                        <span className="block">{itemReasonLabel(item)}</span>
                        <span className="block">{itemSource(item).label}</span>
                    </ItemDescription>
                </ItemContent>
                {stateLabel && (
                    <ItemActions className="self-start">
                        <Badge variant={item.state === 'done' ? 'completed' : 'default'}>{stateLabel}</Badge>
                    </ItemActions>
                )}
            </Item>
            {report && (report.priority || report.pull_request_url || report.summary) && (
                <>
                    <ItemSeparator className="my-0" />
                    <Item size="xs">
                        <ItemContent className="min-w-0 gap-1.5">
                            {report.priority && (
                                <TodayHoverCardFact label="Priority">{report.priority}</TodayHoverCardFact>
                            )}
                            {report.pull_request_url && (
                                <TodayHoverCardFact label="PR">
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
                                        <span className="truncate">{pullRequestState?.label ?? 'Pull request'}</span>
                                    </LinkPrimitive>
                                </TodayHoverCardFact>
                            )}
                            {report.summary && (
                                // Three lines say what the report is about without turning the card into the report.
                                <Text size="xs" variant="muted" className="line-clamp-3 leading-snug break-words">
                                    {report.summary}
                                </Text>
                            )}
                        </ItemContent>
                    </Item>
                </>
            )}
            {metric && metricParts && (
                <>
                    <ItemSeparator className="my-0" />
                    <Item size="xs">
                        <ItemContent className="min-w-0 gap-1">
                            <div className="flex items-baseline justify-between gap-2">
                                <Text size="xs" variant="muted" render={<span />} className="truncate">
                                    {metric.title}
                                </Text>
                                <Text
                                    size="xs"
                                    render={<span translate="no" />}
                                    className="shrink-0 font-semibold tabular-nums"
                                >
                                    {`${metricParts.value} ${metricParts.unit}`}
                                </Text>
                            </div>
                            {series.length > 1 && (
                                <Sparkline
                                    data={series}
                                    theme={theme}
                                    type={reportMetricChartType(metric)}
                                    height={32}
                                    dataAttr="today-report-hover-card-sparkline"
                                />
                            )}
                        </ItemContent>
                    </Item>
                </>
            )}
        </div>
    )
}
