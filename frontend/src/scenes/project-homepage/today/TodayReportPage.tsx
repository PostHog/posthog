import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconExternal } from '@posthog/icons'
import {
    Avatar,
    AvatarFallback,
    Badge,
    Button,
    type ButtonProps,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
    Heading,
    Skeleton,
    SkeletonText,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { ReportChart } from 'products/signals/frontend/inbox/components/detail/ReportChart'
import { ReportSummaryBody } from 'products/signals/frontend/inbox/components/detail/ReportSummaryBody'

import { TodayIcon } from './TodayIcon'
import { TodayReportEvidence } from './TodayReportEvidence'
import { todayReportLogic } from './todayReportLogic'
import { TodayReportPrompts } from './TodayReportPrompts'
import { TodaySampleBanner } from './TodaySampleBanner'
import { isSampleReportId } from './todaySampleReports'
import { reportIcon, reportMeta, reportTitle } from './todaySignalReports'

interface ReportLinkButtonProps {
    to: string
    variant: ButtonProps['variant']
    external?: boolean
    disabledReason?: string
    dataAttr: string
    children: ReactNode
}

/** A link styled as a button. A sample report can't be opened elsewhere, so it turns into a disabled button that says why. */
function ReportLinkButton({
    to,
    variant,
    external = false,
    disabledReason,
    dataAttr,
    children,
}: ReportLinkButtonProps): JSX.Element {
    if (disabledReason) {
        return (
            <Tooltip>
                <TooltipTrigger render={<Button variant={variant} size="sm" disabled data-attr={dataAttr} />}>
                    {children}
                </TooltipTrigger>
                <TooltipContent>{disabledReason}</TooltipContent>
            </Tooltip>
        )
    }
    return (
        <Button
            variant={variant}
            size="sm"
            render={<LinkPrimitive to={to} target={external ? '_blank' : undefined} />}
            data-attr={dataAttr}
        >
            {children}
        </Button>
    )
}

export function TodayReportPage({ reportId }: { reportId: string }): JSX.Element {
    const logic = todayReportLogic({ reportId })
    const { currentReport, reportFailed, fullReportLoading, chartPlacements, trailingCharts, reportUrl } =
        useValues(logic)
    const { loadFullReport } = useActions(logic)
    const sampleDisabledReason = isSampleReportId(reportId) ? 'This is a sample report.' : undefined

    if (!currentReport) {
        return reportFailed ? (
            <>
                <TodaySampleBanner />
                <Empty>
                    <EmptyHeader>
                        <EmptyTitle>Couldn’t open this report</EmptyTitle>
                        <EmptyDescription>
                            It may have been deleted, or the request failed. Try again, or go back to today’s briefing.
                        </EmptyDescription>
                    </EmptyHeader>
                    <EmptyContent className="flex-row justify-center">
                        <Button
                            variant="primary"
                            loading={fullReportLoading}
                            onClick={() => loadFullReport()}
                            data-attr="today-report-retry"
                        >
                            Try again
                        </Button>
                        <Button
                            variant="outline"
                            render={<LinkPrimitive to={urls.projectHomepage()} />}
                            data-attr="today-report-missing-home"
                        >
                            Back to Home
                        </Button>
                    </EmptyContent>
                </Empty>
            </>
        ) : (
            <div className="flex flex-col gap-4" aria-busy>
                <Skeleton className="h-4 w-48" />
                <Skeleton className="h-8 w-3/4" />
                <SkeletonText lines={4} />
            </div>
        )
    }

    return (
        <>
            <TodaySampleBanner />
            <article className="flex flex-col gap-4">
                <div className="flex items-center gap-2">
                    <Avatar size="sm">
                        <AvatarFallback>
                            <TodayIcon icon={reportIcon(currentReport)} />
                        </AvatarFallback>
                    </Avatar>
                    <Text size="xs" variant="muted" render={<span />} className="font-mono uppercase">
                        {reportMeta(currentReport)}
                    </Text>
                    {currentReport.priority && <Badge>{currentReport.priority}</Badge>}
                </div>
                <Heading size="xl" render={<h1 />}>
                    {reportTitle(currentReport)}
                </Heading>
                <div className="flex flex-wrap gap-2">
                    {currentReport.implementation_pr_url && (
                        <ReportLinkButton
                            to={currentReport.implementation_pr_url}
                            variant="primary"
                            external
                            disabledReason={sampleDisabledReason}
                            dataAttr="today-report-pull-request"
                        >
                            Review the pull request
                            <IconExternal />
                        </ReportLinkButton>
                    )}
                    <ReportLinkButton
                        to={urls.inboxReport('reports', currentReport.id)}
                        variant="outline"
                        disabledReason={sampleDisabledReason}
                        dataAttr="today-report-open-inbox"
                    >
                        Open in Inbox
                    </ReportLinkButton>
                </div>
                {currentReport.summary ? (
                    // The summary and charts are shared with the Inbox, so they stay on LemonUI.
                    <div data-not-quill>
                        <ReportSummaryBody summary={currentReport.summary} chartPlacements={chartPlacements} />
                    </div>
                ) : (
                    <Text variant="muted">No summary yet. An agent is still investigating.</Text>
                )}
                {trailingCharts.length > 0 && (
                    <div data-not-quill className="flex flex-col gap-5">
                        {trailingCharts.map((chart) => (
                            <ReportChart key={chart.chart_id} chartId={chart.chart_id} />
                        ))}
                    </div>
                )}
            </article>
            <TodayReportEvidence reportId={currentReport.id} />
            <TodayReportPrompts report={currentReport} reportUrl={reportUrl} />
        </>
    )
}
