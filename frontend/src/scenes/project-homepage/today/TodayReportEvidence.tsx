import { useValues } from 'kea'

import { Button, Heading, Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SignalCard } from 'products/signals/frontend/inbox/SignalCard'

import { todayReportLogic } from './todayReportLogic'
import { isSampleReportId } from './todaySampleReports'

const SHOWN_SIGNAL_COUNT = 3

/** The newest signals behind the report. The full list stays in the Inbox. */
export function TodayReportEvidence({ reportId }: { reportId: string }): JSX.Element {
    const { signals, reportSignals, reportSignalsLoading } = useValues(todayReportLogic({ reportId }))
    const inboxUrl = urls.inboxReport('reports', reportId)

    return (
        <section className="flex flex-col gap-3" aria-label="Evidence">
            <Heading size="sm" render={<h2 />}>
                {reportSignals === null
                    ? 'Evidence'
                    : `Evidence · ${signals.length} ${signals.length === 1 ? 'signal' : 'signals'}`}
            </Heading>
            {reportSignals === null && reportSignalsLoading ? (
                <div className="flex flex-col gap-3">
                    <Skeleton className="h-20" />
                    <Skeleton className="h-20" />
                </div>
            ) : reportSignals === null ? (
                <div className="flex flex-wrap items-center gap-2">
                    <Text size="sm" variant="muted">
                        Couldn’t load the evidence.
                    </Text>
                    <Button
                        variant="link"
                        size="sm"
                        render={<LinkPrimitive to={inboxUrl} />}
                        data-attr="today-evidence-inbox"
                    >
                        Open the report in the Inbox
                    </Button>
                </div>
            ) : signals.length === 0 ? (
                <Text size="sm" variant="muted">
                    No signals are attached to this report yet.
                </Text>
            ) : (
                <div className="flex flex-col gap-3">
                    {/* Signal cards are shared with the Inbox, so they stay on LemonUI. */}
                    <div data-not-quill className="flex flex-col gap-3">
                        {signals.slice(0, SHOWN_SIGNAL_COUNT).map((signal) => (
                            <SignalCard key={signal.signal_id} signal={signal} />
                        ))}
                    </div>
                    {signals.length > SHOWN_SIGNAL_COUNT && !isSampleReportId(reportId) && (
                        <Button
                            variant="link"
                            size="sm"
                            className="self-start"
                            render={<LinkPrimitive to={inboxUrl} />}
                            data-attr="today-evidence-inbox"
                        >
                            {`See all ${signals.length} signals in the Inbox`}
                        </Button>
                    )}
                </div>
            )}
        </section>
    )
}
