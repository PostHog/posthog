import { useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { SignalCard } from 'products/signals/frontend/inbox/SignalCard'

import { todayReportLogic } from './todayReportLogic'

const SHOWN_SIGNAL_COUNT = 3

/** The newest signals behind the report. The full list stays in the Inbox. */
export function TodayReportEvidence({ reportId }: { reportId: string }): JSX.Element {
    const { signals, reportSignals, reportSignalsLoading } = useValues(todayReportLogic({ reportId }))
    const inboxUrl = urls.inboxReport('reports', reportId)

    return (
        <section className="TodayEvidence" aria-label="Evidence">
            <div className="Today__label">
                {reportSignals === null
                    ? 'Evidence'
                    : `Evidence · ${signals.length} ${signals.length === 1 ? 'signal' : 'signals'}`}
            </div>
            {reportSignals === null && reportSignalsLoading ? (
                <div className="flex flex-col gap-3">
                    <LemonSkeleton className="h-20" />
                    <LemonSkeleton className="h-20" />
                </div>
            ) : reportSignals === null ? (
                <p className="TodayEvidence__note">
                    <span>Couldn’t load the evidence. </span>
                    <Link to={inboxUrl} data-attr="today-evidence-inbox">
                        Open the report in the Inbox
                    </Link>
                    <span> to see it there.</span>
                </p>
            ) : signals.length === 0 ? (
                <p className="TodayEvidence__note">No signals are attached to this report yet.</p>
            ) : (
                <div className="flex flex-col gap-3">
                    {signals.slice(0, SHOWN_SIGNAL_COUNT).map((signal) => (
                        <SignalCard key={signal.signal_id} signal={signal} />
                    ))}
                    {signals.length > SHOWN_SIGNAL_COUNT && (
                        <Link to={inboxUrl} className="text-sm" data-attr="today-evidence-inbox">
                            {`See all ${signals.length} signals in the Inbox`}
                        </Link>
                    )}
                </div>
            )}
        </section>
    )
}
