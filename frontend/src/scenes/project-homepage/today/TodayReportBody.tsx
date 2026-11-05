import type {
    ImplementationSlotClaim,
    ReportTaskEntry,
} from 'products/signals/frontend/inbox/logics/inboxReportDetailLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'

import { TodayReportAbstract } from './TodayReportAbstract'
import { TodayReportEvidence } from './TodayReportEvidence'
import { TodayReportFeedback } from './TodayReportFeedback'
import { TodayReportHeader } from './TodayReportHeader'
import { TodayReportNextStep } from './TodayReportNextStep'
import { TodayReportProposal } from './TodayReportProposal'

interface TodayReportLiveState {
    reportTaskToOpen: ReportTaskEntry | null
    implementationSlotClaim: ImplementationSlotClaim | null
}

/** `linksToInbox` is off when the page renders inside the inbox, where those links would point to itself. */
export function TodayReportBody({
    report,
    live,
    linksToInbox = true,
}: {
    report: SignalReport
    live: TodayReportLiveState | null
    linksToInbox?: boolean
}): JSX.Element {
    return (
        <article className="TodayReportArticle flex flex-col gap-10">
            <div className="flex flex-col gap-5">
                <TodayReportHeader report={report} linksToInbox={linksToInbox} />
                <TodayReportAbstract report={report} />
            </div>
            <section className="flex flex-col gap-4 empty:hidden" aria-label="Proposal">
                <TodayReportProposal reportId={report.id} />
                <TodayReportNextStep
                    report={report}
                    reportTaskToOpen={live?.reportTaskToOpen ?? null}
                    slotClaim={live?.implementationSlotClaim ?? null}
                />
            </section>
            <TodayReportEvidence report={report} linksToInbox={linksToInbox} />
            {live && (
                <footer>
                    <TodayReportFeedback report={report} />
                </footer>
            )}
        </article>
    )
}
