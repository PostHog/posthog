import { useValues } from 'kea'

import { Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { todayReportLogic } from './todayReportLogic'
import { groupSignals } from './todayReportPresentation'
import { TodayReportSignalGroup } from './TodayReportSignalGroup'
import { TodayReportSignalList } from './TodayReportSignalList'
import { TodayReportSignalRow } from './TodayReportSignalRow'

export function TodayReportEvidence({ reportId }: { reportId: string }): JSX.Element {
    const { signals, reportSignals, reportSignalsLoading } = useValues(todayReportLogic({ reportId }))
    const groups = groupSignals(signals)
    const count =
        groups.length > 1
            ? `${pluralize(signals.length, 'signal')} from ${groups.length} sources`
            : pluralize(signals.length, 'signal')

    return (
        <section className="flex flex-col gap-2" aria-label="Evidence" data-attr="today-report-evidence">
            <div className="flex items-center justify-between gap-3">
                <Text size="sm" render={<h2 />} className="font-semibold">
                    Evidence
                </Text>
                {reportSignals !== null && signals.length > 0 && (
                    <Text size="xs" variant="muted">
                        {count}
                    </Text>
                )}
            </div>
            {reportSignals === null && reportSignalsLoading ? (
                <div className="flex flex-col gap-2">
                    <Skeleton className="h-12 w-full" />
                    <Skeleton className="h-12 w-full" />
                </div>
            ) : reportSignals === null ? (
                <Text size="sm" variant="muted" render={<p />}>
                    <span>Couldn’t load the evidence. </span>
                    <LinkPrimitive to={urls.inboxReport('reports', reportId)} data-attr="today-evidence-inbox">
                        Open the report in the Inbox
                    </LinkPrimitive>
                    <span> to see it there.</span>
                </Text>
            ) : signals.length === 0 ? (
                <Text size="sm" variant="muted" render={<p />}>
                    No signals are attached to this report yet.
                </Text>
            ) : groups.length === 1 ? (
                <div className="border-y border-border">
                    <TodayReportSignalList reportId={reportId} signals={signals} showIcon />
                </div>
            ) : (
                <div className="flex flex-col divide-y divide-border border-y border-border">
                    {groups.map((group) =>
                        group.signals.length === 1 ? (
                            <TodayReportSignalRow
                                key={group.source}
                                reportId={reportId}
                                signal={group.signals[0]}
                                showIcon
                            />
                        ) : (
                            <TodayReportSignalGroup key={group.source} reportId={reportId} group={group} />
                        )
                    )}
                </div>
            )}
        </section>
    )
}
