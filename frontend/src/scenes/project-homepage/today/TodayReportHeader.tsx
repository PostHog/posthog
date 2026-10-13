import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheckCircle, IconDocument, IconEllipsis, IconHide } from '@posthog/icons'
import { Badge, Button, Heading, Text, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { SHEET_PARTS } from '~/layout/today/todayMenuParts'
import { TodaySheetMenu } from '~/layout/today/TodaySheetMenu'
import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { SignalReport } from 'products/signals/frontend/inbox/types'
import { hasOpenImplementationPr } from 'products/signals/frontend/inbox/utils/reportActions'
import { displayConventionalCommitTitle } from 'products/signals/frontend/inbox/utils/reportPresentation'

import { TodayActionButton } from './TodayActionButton'
import { itemStateLabel } from './todayBriefingItems'
import { TodayEvidenceAge } from './TodayEvidenceAge'
import { TodayReportVerdict, todayLogic } from './todayLogic'
import { TodayMarkedText } from './TodayMarkedText'
import { resolveDisabledReason } from './todayNextStep'
import { todayReportLogic } from './todayReportLogic'
import { SAMPLE_REPORT_REASON } from './todaySampleReports'
import { priorityBadgeVariant, reportSourceLine, reportTitle } from './todaySignalReports'

function PhoneActions({
    report,
    stateBadge,
    sampleReason,
    giveVerdict,
}: {
    report: SignalReport
    stateBadge: JSX.Element | null
    sampleReason: string | null
    giveVerdict: (verdict: TodayReportVerdict) => void
}): JSX.Element {
    const [open, setOpen] = useState(false)
    const resolveReason = resolveDisabledReason(report, sampleReason)
    // The sheet description already gives the sample reason, so only a different reason needs its own line.
    const resolveNote = resolveReason !== sampleReason ? resolveReason : null
    const { Item } = SHEET_PARTS

    return (
        <div className="-me-1.5 flex shrink-0 items-center gap-1">
            {stateBadge}
            <Button
                size="icon-sm"
                variant="link-muted"
                aria-label="Report actions"
                onClick={() => setOpen(true)}
                data-attr="today-report-actions"
            >
                <IconEllipsis />
            </Button>
            <TodaySheetMenu
                open={open}
                onOpenChange={setOpen}
                title={reportTitle(report)}
                description={sampleReason ?? undefined}
            >
                {!sampleReason && (
                    <Item to={urls.inboxReport('reports', report.id)} dataAttr="today-report-open-inbox">
                        <IconDocument />
                        Open the full report
                    </Item>
                )}
                {!stateBadge && (
                    <>
                        <Item
                            onClick={() => giveVerdict('resolve')}
                            disabled={!!resolveReason}
                            dataAttr="today-report-resolve"
                        >
                            <IconCheckCircle className={cn(resolveNote && 'self-start')} />
                            <span className="flex flex-col">
                                <span>Resolve</span>
                                {resolveNote && (
                                    <Text size="xs" variant="muted" render={<span />}>
                                        {resolveNote}
                                    </Text>
                                )}
                            </span>
                        </Item>
                        <Item
                            onClick={() => giveVerdict('dismiss')}
                            disabled={!!sampleReason}
                            dataAttr="today-report-dismiss"
                        >
                            <IconHide />
                            Dismiss
                        </Item>
                    </>
                )}
            </TodaySheetMenu>
        </div>
    )
}

export function TodayReportHeader({ report }: { report: SignalReport }): JSX.Element {
    const { requestReportVerdict } = useActions(todayLogic)
    const { phoneLayout } = useValues(todayShellLogic)
    const { lead, leadMarks, shownKeyClauses, reportState, isSample } = useValues(
        todayReportLogic({ reportId: report.id })
    )
    const sampleReason = isSample ? SAMPLE_REPORT_REASON : null
    const stateLabel = itemStateLabel({ state: reportState })
    const stateBadge = stateLabel ? (
        <Badge variant={reportState === 'done' ? 'completed' : 'default'}>{stateLabel}</Badge>
    ) : null
    const sources = reportSourceLine(report)
    const updated = dayjs(report.updated_at)
    const stillInvestigating = !report.summary?.trim()

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
                    className={cn(
                        'flex flex-1 basis-0 items-center gap-2 whitespace-nowrap',
                        phoneLayout ? 'min-w-0' : 'min-w-64'
                    )}
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
                        {!phoneLayout && <span>Updated&nbsp;</span>}
                        <span translate="no">{updated.fromNow()}</span>
                    </time>
                </Text>
                {phoneLayout ? (
                    <PhoneActions
                        report={report}
                        stateBadge={stateBadge}
                        sampleReason={sampleReason}
                        giveVerdict={giveVerdict}
                    />
                ) : (
                    <div className="-mx-2 flex shrink-0 items-center gap-0.5">
                        {!isSample && (
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
                        )}
                        {stateBadge ?? (
                            <>
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
                            </>
                        )}
                    </div>
                )}
            </div>
            <div className="flex flex-col gap-2">
                <Heading size="xl" render={<h1 />} className="leading-snug text-balance">
                    {capitalizeFirstLetter(displayConventionalCommitTitle(report.title, 'Untitled report'))}
                </Heading>
                {lead && (
                    <div data-today-figures>
                        <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                            <TodayMarkedText
                                markdown={lead}
                                marked={leadMarks}
                                keyClauses={shownKeyClauses?.lead ?? []}
                                reportId={report.id}
                            />
                        </Text>
                    </div>
                )}
                {stillInvestigating && (
                    <Text variant="muted" render={<p />}>
                        No summary yet. An agent is still investigating.
                    </Text>
                )}
                <TodayEvidenceAge report={report} />
            </div>
        </header>
    )
}
