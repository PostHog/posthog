import { useValues } from 'kea'

import { Button, Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SignalReport } from 'products/signals/frontend/inbox/types'

import { todayReportLogic } from './todayReportLogic'
import { TodayReportSectionTitle } from './TodayReportSectionTitle'
import { TodayReportSignalRow } from './TodayReportSignalRow'

function EvidenceRows({ reportId }: { reportId: string }): JSX.Element {
    const { signals, shownEvidence, reportSignals, reportSignalsLoading } = useValues(todayReportLogic({ reportId }))
    if (reportSignals === null && reportSignalsLoading) {
        return (
            <div className="flex flex-col gap-6 py-3">
                <Skeleton className="h-3.5 w-11/12" />
                <Skeleton className="h-3.5 w-3/4" />
                <Skeleton className="h-3.5 w-5/6" />
            </div>
        )
    }
    if (reportSignals === null) {
        return (
            <Text size="sm" variant="muted" render={<p />}>
                <span>Couldn’t load the evidence. </span>
                <LinkPrimitive to={urls.inboxReport('reports', reportId)} data-attr="today-evidence-inbox">
                    Open the full report
                </LinkPrimitive>
                <span> to see it.</span>
            </Text>
        )
    }
    if (signals.length === 0) {
        return (
            <Text size="sm" variant="muted" render={<p />}>
                No signals are attached to this report yet.
            </Text>
        )
    }
    return (
        <div className="-mx-2 flex flex-col">
            {shownEvidence.map((signal) => (
                <TodayReportSignalRow key={signal.signal_id} reportId={reportId} signal={signal} />
            ))}
        </div>
    )
}

export function TodayReportEvidence({ report }: { report: SignalReport }): JSX.Element {
    const { shownEvidence, evidenceCount } = useValues(todayReportLogic({ reportId: report.id }))
    const fullReport = urls.inboxReport('reports', report.id)

    return (
        <section className="flex flex-col gap-0.5" aria-label="Evidence" data-attr="today-report-evidence">
            <div className="flex items-baseline justify-between gap-3">
                <TodayReportSectionTitle>Evidence</TodayReportSectionTitle>
                {evidenceCount > shownEvidence.length && (
                    <Button
                        variant="link-muted"
                        size="sm"
                        className="-me-2"
                        nativeButton={false}
                        render={<LinkPrimitive to={fullReport} />}
                        data-attr="today-report-evidence-all"
                    >
                        {`See all ${evidenceCount}`}
                    </Button>
                )}
            </div>
            <EvidenceRows reportId={report.id} />
        </section>
    )
}
