import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { evaluationReportLogic } from '../evaluationReportLogic'
import { ReportSectionContent } from './EvaluationReportViewer'

/**
 * The newest report's headline and summary, on the tab people actually open. Few people visit the Reports tab,
 * so the report comes to them here, with a link to the full version.
 */
export function EvaluationLatestReport({
    evaluationId,
    onOpenReports,
}: {
    evaluationId: string
    onOpenReports: () => void
}): JSX.Element | null {
    const { reportRuns } = useValues(evaluationReportLogic({ evaluationId }))

    const latest = [...reportRuns].sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
    if (!latest) {
        return null
    }
    const content = latest.content
    const [summary] = content.sections ?? []

    return (
        <section className="mb-4 rounded border bg-surface-primary p-4" data-attr="llma-evaluation-latest-report">
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex flex-col gap-1 min-w-0">
                    <span className="text-xs text-secondary">{`Latest report, ${dayjs(latest.created_at).fromNow()}`}</span>
                    <h3 className="mb-0 text-base font-semibold">{content.title || 'Evaluation report'}</h3>
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={onOpenReports}
                    data-attr="llma-evaluation-latest-report-open"
                >
                    Read the full report
                </LemonButton>
            </div>
            {summary?.content && (
                // Clipped to a few lines, since the full report is one click away.
                <div className="mt-2 max-h-28 overflow-hidden">
                    <ReportSectionContent section={summary} citations={content.citations ?? []} />
                </div>
            )}
        </section>
    )
}
