import type {
    ImplementationSlotClaim,
    ReportTaskEntry,
} from 'products/signals/frontend/inbox/logics/inboxReportDetailLogic'
import { SignalReport } from 'products/signals/frontend/inbox/types'
import type { BriefingItemStateEnumApi } from 'products/today/frontend/generated/api.schemas'

import { TodayReportAbstract } from './TodayReportAbstract'
import { TodayReportEvidence } from './TodayReportEvidence'
import { TodayReportFeedback } from './TodayReportFeedback'
import { TodayReportHeader } from './TodayReportHeader'
import { TodayReportNextStep } from './TodayReportNextStep'
import { TodayReportSections, TodayResearchNote, todayNextStep } from './todayReportPresentation'
import { TodayReportProposal } from './TodayReportProposal'

export interface TodayReportLiveState {
    reportTaskToOpen: ReportTaskEntry | null
    implementationSlotClaim: ImplementationSlotClaim | null
    research: TodayResearchNote[]
}

export function TodayReportBody({
    report,
    reportState,
    reportUrl,
    sections,
    live,
}: {
    report: SignalReport
    reportState: BriefingItemStateEnumApi
    reportUrl: string
    sections: TodayReportSections
    live: TodayReportLiveState | null
}): JSX.Element {
    const slotClaim = live?.implementationSlotClaim ?? null
    const research = live?.research ?? []
    const step = todayNextStep(report, { taskRunning: slotClaim === 'in_flight', slotClaimed: slotClaim !== null })
    return (
        <>
            <article className="TodayReportArticle @container flex max-w-150 flex-col gap-10">
                <div className="flex flex-col gap-5">
                    <TodayReportHeader
                        report={report}
                        reportState={reportState}
                        sections={sections}
                        research={research}
                    />
                    <TodayReportAbstract report={report} sections={sections} research={research} />
                </div>
                <section className="flex flex-col gap-4" aria-label="Proposal">
                    <TodayReportProposal report={report} sections={sections} />
                    <TodayReportNextStep
                        report={report}
                        reportState={reportState}
                        reportUrl={reportUrl}
                        reportTaskToOpen={live?.reportTaskToOpen ?? null}
                        step={step}
                    />
                </section>
                <TodayReportEvidence report={report} />
                {live && (
                    <footer>
                        <TodayReportFeedback report={report} />
                    </footer>
                )}
            </article>
        </>
    )
}
