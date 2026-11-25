import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { LatestReportPreview } from '../components/LatestReportPreview'
import { evaluationReportDrawerLogic } from '../evaluationReportDrawerLogic'
import { evaluationLatestReportRunLogic } from './evaluationLatestReportRunLogic'

/** The evaluation's newest report in the overview drawer. The button opens it in the report drawer on top. */
export function EvaluationLatestReportCard({ evaluationId }: { evaluationId: string }): JSX.Element | null {
    const { latestRun, latestRunLoadFailed, latestRunLoading } = useValues(
        evaluationLatestReportRunLogic({ evaluationId })
    )
    const { loadLatestRun } = useActions(evaluationLatestReportRunLogic({ evaluationId }))
    const { openRun } = useActions(evaluationReportDrawerLogic({ evaluationId }))
    if (latestRunLoadFailed) {
        return (
            <section className="flex items-center gap-2 rounded border bg-surface-primary p-3 text-sm">
                <span>Couldn't load the latest report.</span>
                <LemonButton type="secondary" size="small" loading={latestRunLoading} onClick={() => loadLatestRun()}>
                    Try again
                </LemonButton>
            </section>
        )
    }
    if (!latestRun) {
        return null
    }
    return (
        <LatestReportPreview
            run={latestRun}
            className="p-3"
            // The card is a preview in a busy drawer, and the button opens the whole report.
            summaryClassName="line-clamp-4"
            action={
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => openRun(latestRun.id, 'overview_card')}
                    data-attr="llma-evaluation-overview-latest-report"
                >
                    Read the report
                </LemonButton>
            }
        />
    )
}
