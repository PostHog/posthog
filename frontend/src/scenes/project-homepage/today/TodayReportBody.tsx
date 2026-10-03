import { useValues } from 'kea'

import type {
    ImplementationSlotClaim,
    ReportTaskEntry,
} from 'products/signals/frontend/inbox/logics/inboxReportDetailLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'

import { TodayResearchNote, markedFigures } from './todayFigureSources'
import { TodayReportAbstract } from './TodayReportAbstract'
import { TodayReportEvidence } from './TodayReportEvidence'
import { TodayReportFeedback } from './TodayReportFeedback'
import { TodayReportHeader } from './TodayReportHeader'
import { todayReportLogic } from './todayReportLogic'
import { TodayReportNextStep } from './TodayReportNextStep'
import { TodayReportProposal } from './TodayReportProposal'

interface TodayReportLiveState {
    reportTaskToOpen: ReportTaskEntry | null
    implementationSlotClaim: ImplementationSlotClaim | null
    research: TodayResearchNote[]
}

export function TodayReportBody({
    report,
    live,
}: {
    report: SignalReport
    live: TodayReportLiveState | null
}): JSX.Element {
    const { signals, lead, impactText } = useValues(todayReportLogic({ reportId: report.id }))
    const evidence = { signals, research: live?.research ?? [], summary: report.summary }
    const leadMarks = markedFigures(lead, evidence)
    return (
        <article className="TodayReportArticle @container flex max-w-150 flex-col gap-10">
            <div className="flex flex-col gap-5">
                <TodayReportHeader report={report} leadMarks={leadMarks} />
                <TodayReportAbstract
                    report={report}
                    leadIsMeasured={leadMarks.length > 0}
                    impactMarks={markedFigures(impactText, evidence)}
                />
            </div>
            <section className="flex flex-col gap-4" aria-label="Proposal">
                <TodayReportProposal reportId={report.id} />
                <TodayReportNextStep
                    report={report}
                    reportTaskToOpen={live?.reportTaskToOpen ?? null}
                    slotClaim={live?.implementationSlotClaim ?? null}
                />
            </section>
            <TodayReportEvidence report={report} />
            {live && (
                <footer>
                    <TodayReportFeedback report={report} />
                </footer>
            )}
        </article>
    )
}
