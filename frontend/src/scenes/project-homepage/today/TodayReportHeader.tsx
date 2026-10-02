import { useActions } from 'kea'

import { IconCheckCircle, IconExternal, IconHide } from '@posthog/icons'
import { Badge, Heading, Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SignalReport } from 'products/signals/frontend/inbox/types'
import { canResolveReport, hasOpenImplementationPr } from 'products/signals/frontend/inbox/utils/reportActions'
import type { BriefingItemStateEnumApi } from 'products/today/frontend/generated/api.schemas'

import { TodayActionButton } from './TodayActionButton'
import { itemStateLabel } from './todayBriefingItems'
import { TodayIcon } from './TodayIcon'
import { TodayReportVerdict, todayLogic } from './todayLogic'
import { isSampleReportId } from './todaySampleReports'
import { reportIcon, reportSource, reportTitle } from './todaySignalReports'

const SAMPLE_REASON = 'This is a sample report.'

export function TodayReportHeader({
    report,
    reportState,
}: {
    report: SignalReport
    reportState: BriefingItemStateEnumApi
}): JSX.Element {
    const { requestReportVerdict } = useActions(todayLogic)
    const source = reportSource(report)
    const sampleReason = isSampleReportId(report.id) ? SAMPLE_REASON : null
    const stateLabel = itemStateLabel({ state: reportState })

    const giveVerdict = (verdict: TodayReportVerdict): void =>
        requestReportVerdict(
            { reportId: report.id, title: reportTitle(report), hasOpenPullRequest: hasOpenImplementationPr(report) },
            verdict,
            'report_page'
        )

    return (
        <header className="flex flex-col gap-2">
            <div className="flex min-h-7 items-center justify-between gap-3">
                <Text
                    size="xs"
                    variant="muted"
                    render={<div />}
                    className="flex min-w-0 items-center gap-1.5 whitespace-nowrap"
                >
                    <span aria-hidden className="flex size-4 shrink-0 items-center justify-center [&_svg]:size-3.5">
                        <TodayIcon icon={reportIcon(report)} />
                    </span>
                    {report.priority && <span className="font-semibold text-foreground">{report.priority}</span>}
                    {report.priority && <span aria-hidden>·</span>}
                    <span className="truncate">{source.label}</span>
                    <span aria-hidden>·</span>
                    <span>{dayjs(report.updated_at).fromNow()}</span>
                    <span aria-hidden>·</span>
                    <LinkPrimitive
                        to={urls.inboxReport('reports', report.id)}
                        className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
                        data-attr="today-report-open-inbox"
                    >
                        Full report
                        <IconExternal className="size-3" />
                    </LinkPrimitive>
                </Text>
                {stateLabel ? (
                    <Badge variant={reportState === 'done' ? 'completed' : 'default'}>{stateLabel}</Badge>
                ) : (
                    <div className="-me-2 flex shrink-0 items-center gap-0.5">
                        <TodayActionButton
                            size="sm"
                            variant={report.already_addressed ? 'outline' : 'default'}
                            onClick={() => giveVerdict('resolve')}
                            disabledReason={
                                sampleReason ??
                                (canResolveReport(report)
                                    ? null
                                    : 'You can resolve a report only after the agent finishes its research.')
                            }
                            tooltip="Mark this report as done"
                            data-attr="today-report-resolve"
                        >
                            <IconCheckCircle />
                            Resolve
                        </TodayActionButton>
                        <TodayActionButton
                            size="sm"
                            onClick={() => giveVerdict('dismiss')}
                            disabledReason={sampleReason}
                            tooltip="Dismiss this report from your inbox"
                            data-attr="today-report-dismiss"
                        >
                            <IconHide />
                            Dismiss
                        </TodayActionButton>
                    </div>
                )}
            </div>
            <Heading size="lg" render={<h1 />} className="text-balance">
                {reportTitle(report)}
            </Heading>
        </header>
    )
}
