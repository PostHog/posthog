import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconDocument, IconHide } from '@posthog/icons'
import { Badge, Heading, Text } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { SignalReport } from 'products/signals/frontend/inbox/types'
import { canResolveReport, hasOpenImplementationPr } from 'products/signals/frontend/inbox/utils/reportActions'
import { displayConventionalCommitTitle } from 'products/signals/frontend/inbox/utils/reportPresentation'
import type { BriefingItemStateEnumApi } from 'products/today/frontend/generated/api.schemas'

import { TodayActionButton } from './TodayActionButton'
import { itemStateLabel } from './todayBriefingItems'
import { TodayEvidenceAge } from './TodayEvidenceAge'
import { renderedText } from './todayKeyClauses'
import { TodayReportVerdict, todayLogic } from './todayLogic'
import { TodayMarkedText } from './TodayMarkedText'
import { todayReportLogic } from './todayReportLogic'
import {
    TodayReportSections,
    TodayResearchNote,
    figureCardContent,
    lastOccurrence,
    markedFigures,
    priorityBadgeVariant,
    scoutLabel,
} from './todayReportPresentation'
import { isSampleReportId } from './todaySampleReports'
import { reportTitle, sourceStyle } from './todaySignalReports'

const SAMPLE_REASON = 'This is a sample report.'
const SHOWN_SOURCES = 2
const SOURCE_LINE_CHARS = 32

function sourceLabels(report: Pick<SignalReport, 'source_products' | 'scout_name'>): string[] {
    return [
        ...new Set(
            (report.source_products ?? []).map((source) =>
                source === 'signals_scout' ? (scoutLabel(report.scout_name) ?? 'Scout') : sourceStyle(source).label
            )
        ),
    ]
}

function sourceLine(report: Pick<SignalReport, 'source_products' | 'scout_name'>): string {
    const labels = sourceLabels(report)
    if (labels.length === 0) {
        return scoutLabel(report.scout_name) ?? sourceStyle(null).label
    }
    const count = labels.slice(0, SHOWN_SOURCES).join(', ').length > SOURCE_LINE_CHARS ? 1 : SHOWN_SOURCES
    const shown = labels.slice(0, count).join(', ')
    return labels.length > count ? `${shown} +${labels.length - count}` : shown
}

export function TodayReportHeader({
    report,
    reportState,
    sections,
    research,
}: {
    report: SignalReport
    reportState: BriefingItemStateEnumApi
    sections: TodayReportSections
    research: TodayResearchNote[]
}): JSX.Element {
    const { requestReportVerdict } = useActions(todayLogic)
    const { signals, keyClauses } = useValues(todayReportLogic({ reportId: report.id }))
    const leadMarks = markedFigures(sections.lead, (figure) =>
        figureCardContent(figure, { signals, research, summary: report.summary, shownText: sections.lead })
    )
    const sampleReason = isSampleReportId(report.id) ? SAMPLE_REASON : null
    const stateLabel = itemStateLabel({ state: reportState })
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
                    <span className="min-w-0 truncate" title={sourceLabels(report).join(', ') || undefined}>
                        {sourceLine(report)}
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
                {sections.lead ? (
                    <div data-today-figures>
                        <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                            <TodayMarkedText
                                markdown={sections.lead}
                                marked={leadMarks}
                                reportId={report.id}
                                keyClauses={keyClauses[renderedText(sections.lead)]}
                            />
                        </Text>
                        <TodayEvidenceAge
                            marked={leadMarks}
                            reportUpdatedAt={report.updated_at}
                            lastSeen={lastOccurrence(signals)}
                        />
                    </div>
                ) : (
                    <Text variant="muted" render={<p />}>
                        No summary yet. An agent is still investigating.
                    </Text>
                )}
            </div>
        </header>
    )
}
