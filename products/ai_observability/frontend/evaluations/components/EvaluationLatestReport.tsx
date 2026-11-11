import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { evaluationReportDrawerLogic } from '../evaluationReportDrawerLogic'
import { evaluationReportLogic } from '../evaluationReportLogic'
import { ReportSectionContent } from './EvaluationReportViewer'

/**
 * The newest report's headline and summary, on the tab people actually open. Few people visit the Reports tab,
 * so the report comes to them here, with a button that opens the full version.
 */
export function EvaluationLatestReport({ evaluationId }: { evaluationId: string }): JSX.Element | null {
    const { reportRuns } = useValues(evaluationReportLogic({ evaluationId }))
    const { openRun } = useActions(evaluationReportDrawerLogic({ evaluationId }))

    // The runs endpoint returns newest first.
    const latest = reportRuns[0]
    if (!latest) {
        return null
    }
    const content = latest.content
    const [summary] = content.sections ?? []

    return (
        <section className="mb-4 rounded border bg-surface-primary p-4" data-attr="llma-evaluation-latest-report">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex flex-col gap-1 min-w-0">
                    <span className="text-xs text-secondary">
                        Latest report, <TZLabel time={latest.created_at} noStyles />
                    </span>
                    <h3 className="mb-0 text-base font-semibold">{content.title || 'Evaluation report'}</h3>
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => openRun(latest.id, 'runs_card')}
                    data-attr="llma-evaluation-latest-report-open"
                >
                    Read the full report
                </LemonButton>
            </div>
            {summary?.content && (
                <div className="mt-2">
                    <ReportSectionContent section={summary} citations={content.citations ?? []} />
                </div>
            )}
        </section>
    )
}
