import { SignalReportEntry } from 'lib/signals/SignalReportEntry'

import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'

import type { TimelineExtra } from '../../components/Chat/MessageList'
import { TeamOnlyBadge } from '../../components/Chat/TeamOnlyBadge'

/**
 * One report, as an entry in the ticket thread.
 *
 * Full width, unlike a message: messages are inset because they belong to one side of the conversation,
 * and this belongs to neither. It keeps the thread's own private-note lock, because the thread is a
 * place where people talk to customers and this was never sent to one.
 */
export function ThreadReportEntry({ report }: { report: SignalReportApi }): JSX.Element {
    return (
        <div className="mb-4">
            <SignalReportEntry
                report={report}
                agentSubject="tickets"
                badge={<TeamOnlyBadge label="Internal" tone="agent" />}
            />
        </div>
    )
}

/** Reports as thread entries, ordered by when each was last updated. */
export function reportTimelineExtras(linkedReports: SignalReportApi[]): TimelineExtra[] {
    return linkedReports.map((report) => ({
        at: report.updated_at,
        element: <ThreadReportEntry key={report.id} report={report} />,
    }))
}
