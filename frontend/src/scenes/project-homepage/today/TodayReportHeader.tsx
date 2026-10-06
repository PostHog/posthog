import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconDocument, IconHide } from '@posthog/icons'
import { Badge, Heading, Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { SignalReport } from 'products/signals/frontend/inbox/types'
import { hasOpenImplementationPr } from 'products/signals/frontend/inbox/utils/reportActions'
import { displayConventionalCommitTitle } from 'products/signals/frontend/inbox/utils/reportPresentation'

import { TodayActionButton } from './TodayActionButton'
import { itemStateLabel } from './todayBriefingItems'
import { TodayInlineMarkdown } from './TodayInlineMarkdown'
import { TodayReportVerdict, todayLogic } from './todayLogic'
import { resolveDisabledReason } from './todayNextStep'
import { todayReportLogic } from './todayReportLogic'
import { priorityBadgeVariant, reportSourceLine, reportTitle } from './todaySignalReports'

const SAMPLE_REASON = 'This is a sample report.'
export function TodayReportHeader({ report }: { report: SignalReport }): JSX.Element {
    const { requestReportVerdict } = useActions(todayLogic)
    const { lead, reportState, isSample } = useValues(todayReportLogic({ reportId: report.id }))
    const sampleReason = isSample ? SAMPLE_REASON : null
    const stateLabel = itemStateLabel({ state: reportState })
    const sources = reportSourceLine(report)
    const updated = dayjs(report.updated_at)

    const giveVerdict = (verdict: TodayReportVerdict): void =>
        requestReportVerdict(
            { reportId: report.id, title: reportTitle(report), hasOpenPullRequest: hasOpenImplementationPr(report) },
            verdict,
            'report_page'
        )

    return (
        <header className="flex flex-col gap-3">
            <div className="flex min-h-7 flex-wrap items-center justify-between gap-x-3 gap-y-1">
                <Text
                    size="xs"
                    variant="muted"
                    render={<div />}
                    className="flex min-w-0 flex-1 basis-0 items-center gap-2 whitespace-nowrap"
                >
                    {report.priority && (
                        <Badge variant={priorityBadgeVariant(report.priority)}>{report.priority}</Badge>
                    )}
                    <span className="min-w-0 truncate" title={sources.title || undefined}>
                        {sources.line}
                    </span>
                    <span aria-hidden className="-mx-0.5">
                        ·
                    </span>
                    <time dateTime={report.updated_at} title={updated.format('LLL')}>
                        Updated {updated.fromNow()}
                    </time>
                </Text>
                {stateLabel ? (
                    <Badge variant={reportState === 'done' ? 'completed' : 'default'}>{stateLabel}</Badge>
                ) : (
                    <div className="-me-2 flex shrink-0 items-center gap-0.5">
                        <TodayActionButton
                            size="sm"
                            variant="link-muted"
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.inboxReport('reports', report.id)} />}
                            tooltip="Open the full report in the Inbox"
                            data-attr="today-report-open-inbox"
                        >
                            <IconDocument />
                            Full report
                        </TodayActionButton>
                        <TodayActionButton
                            size="sm"
                            variant="link-muted"
                            onClick={() => giveVerdict('resolve')}
                            disabledReason={resolveDisabledReason(report, sampleReason)}
                            tooltip="Mark this report as done"
                            data-attr="today-report-resolve"
                        >
                            <IconCheckCircle />
                            Resolve
                        </TodayActionButton>
                        <TodayActionButton
                            size="sm"
                            variant="link-muted"
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
            <div className="flex flex-col gap-2">
                <Heading size="xl" render={<h1 />} className="leading-snug text-balance">
                    {capitalizeFirstLetter(displayConventionalCommitTitle(report.title, 'Untitled report'))}
                </Heading>
                {lead ? (
                    <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                        <TodayInlineMarkdown markdown={lead} />
                    </Text>
                ) : (
                    <Text variant="muted" render={<p />}>
                        No summary yet. An agent is still investigating.
                    </Text>
                )}
            </div>
        </header>
    )
}
