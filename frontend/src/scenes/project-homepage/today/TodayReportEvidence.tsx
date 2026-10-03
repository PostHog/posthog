import { useValues } from 'kea'

import { Button, Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SignalReport } from 'products/signals/frontend/inbox/types'

import { todayReportLogic } from './todayReportLogic'
import { distinctEvidenceCount, pickEvidence } from './todayReportPresentation'
import { TodayReportSectionTitle } from './TodayReportSectionTitle'
import { TodayReportSignalRow } from './TodayReportSignalRow'

const SHOWN_SIGNALS = 3

export function TodayReportEvidence({ report }: { report: SignalReport }): JSX.Element {
    const { signals, reportSignals, reportSignalsLoading } = useValues(todayReportLogic({ reportId: report.id }))
    const shown = pickEvidence(signals, SHOWN_SIGNALS)
    const distinct = distinctEvidenceCount(signals)
    const fullReport = urls.inboxReport('reports', report.id)

    return (
        <section className="flex flex-col gap-0.5" aria-label="Evidence" data-attr="today-report-evidence">
            <div className="flex items-baseline justify-between gap-3">
                <TodayReportSectionTitle>Evidence</TodayReportSectionTitle>
                {distinct > shown.length && (
                    <Button
                        variant="link-muted"
                        size="sm"
                        className="-me-2"
                        nativeButton={false}
                        render={<LinkPrimitive to={fullReport} />}
                        data-attr="today-report-evidence-all"
                    >
                        {`See all ${distinct}`}
                    </Button>
                )}
            </div>
            {reportSignals === null && reportSignalsLoading ? (
                <div className="flex flex-col gap-6 py-3">
                    <Skeleton className="h-3.5 w-11/12" />
                    <Skeleton className="h-3.5 w-3/4" />
                    <Skeleton className="h-3.5 w-5/6" />
                </div>
            ) : reportSignals === null ? (
                <Text size="sm" variant="muted" render={<p />}>
                    <span>Couldn’t load the evidence. </span>
                    <LinkPrimitive to={fullReport} data-attr="today-evidence-inbox">
                        Open the full report
                    </LinkPrimitive>
                    <span> to see it.</span>
                </Text>
            ) : signals.length === 0 ? (
                <Text size="sm" variant="muted" render={<p />}>
                    No signals are attached to this report yet.
                </Text>
            ) : (
                <div className="-mx-2 flex flex-col">
                    {shown.map((signal) => (
                        <TodayReportSignalRow key={signal.signal_id} reportId={report.id} signal={signal} showSource />
                    ))}
                </div>
            )}
        </section>
    )
}
