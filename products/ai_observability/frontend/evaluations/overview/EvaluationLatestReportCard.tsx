import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { ReportSectionContent } from '../components/EvaluationReportViewer'
import { REPORT_RUN_PARAM } from '../evaluationReportDrawerLogic'
import { evaluationReportLogic } from '../evaluationReportLogic'

/** The evaluation's newest report in the overview drawer, linking to the report on the evaluation page. */
export function EvaluationLatestReportCard({
    evaluationId,
    reportUrl,
}: {
    evaluationId: string
    reportUrl: (params: Record<string, string>) => string
}): JSX.Element | null {
    const { reportRuns } = useValues(evaluationReportLogic({ evaluationId }))
    const latest = reportRuns[0]
    if (!latest) {
        return null
    }
    const [summary] = latest.content.sections ?? []
    return (
        <section className="flex flex-col gap-2 rounded border bg-surface-primary p-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="text-xs text-secondary">
                        Latest report, <TZLabel time={latest.created_at} noStyles />
                    </span>
                    <h4 className="mb-0 text-sm font-semibold">{latest.content.title || 'Evaluation report'}</h4>
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    to={reportUrl({ [REPORT_RUN_PARAM]: latest.id })}
                    data-attr="llma-evaluation-overview-latest-report"
                >
                    Read the report
                </LemonButton>
            </div>
            {summary?.content && (
                // The card is a preview in a busy drawer, and the button opens the whole report.
                <div className="line-clamp-4">
                    <ReportSectionContent section={summary} citations={latest.content.citations ?? []} />
                </div>
            )}
        </section>
    )
}
