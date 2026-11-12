import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { LatestReportPreview } from '../components/LatestReportPreview'
import { REPORT_RUN_PARAM } from '../evaluationReportDrawerLogic'
import { markNextDrawerSource } from '../evaluationReportTracking'
import { evaluationLatestReportRunLogic } from './evaluationLatestReportRunLogic'

/** The evaluation's newest report in the overview drawer, linking to the report on the evaluation page. */
export function EvaluationLatestReportCard({
    evaluationId,
    reportUrl,
}: {
    evaluationId: string
    reportUrl: (params: Record<string, string>) => string
}): JSX.Element | null {
    const { latestRun, latestRunLoadFailed, latestRunLoading } = useValues(
        evaluationLatestReportRunLogic({ evaluationId })
    )
    const { loadLatestRun } = useActions(evaluationLatestReportRunLogic({ evaluationId }))
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
                    to={reportUrl({ [REPORT_RUN_PARAM]: latestRun.id })}
                    onClick={() => markNextDrawerSource('overview_card')}
                    data-attr="llma-evaluation-overview-latest-report"
                >
                    Read the report
                </LemonButton>
            }
        />
    )
}
