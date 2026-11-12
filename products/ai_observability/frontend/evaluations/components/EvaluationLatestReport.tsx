import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { evaluationReportDrawerLogic } from '../evaluationReportDrawerLogic'
import { evaluationReportRunsLogic } from '../evaluationReportRunsLogic'
import { LatestReportPreview } from './LatestReportPreview'

/**
 * The newest report's headline and summary, on the tab people actually open. Few people visit the Reports tab,
 * so the report comes to them here, with a button that opens the full version.
 */
export function EvaluationLatestReport({ evaluationId }: { evaluationId: string }): JSX.Element | null {
    const { reportRuns } = useValues(evaluationReportRunsLogic({ evaluationId }))
    const { openRun } = useActions(evaluationReportDrawerLogic({ evaluationId }))

    // The runs endpoint returns newest first.
    const latest = reportRuns[0]
    if (!latest) {
        return null
    }
    return (
        <div className="mb-4" data-attr="llma-evaluation-latest-report">
            <LatestReportPreview
                run={latest}
                className="p-4"
                action={
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => openRun(latest.id, 'runs_card')}
                        data-attr="llma-evaluation-latest-report-open"
                    >
                        Read the full report
                    </LemonButton>
                }
            />
        </div>
    )
}
