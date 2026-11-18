import { combineUrl } from 'kea-router'

import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { EvaluationRun } from '../evaluations/types'

export function EvaluationRunTimestampCell({ run }: { run: EvaluationRun }): JSX.Element {
    if (!run.backfill_id) {
        return <TZLabel time={run.timestamp} />
    }

    const backfillResults = combineUrl(urls.aiObservabilityEvaluation(run.evaluation_id), {
        evaluation_tab: 'runs',
        backfill_id: run.backfill_id,
    }).url

    return (
        <div className="flex items-center gap-2">
            <TZLabel time={run.timestamp} />
            <Tooltip title="A backfill over past data produced this result. Open to see everything that backfill evaluated.">
                <Link to={backfillResults} data-attr="llma-eval-run-backfill-link">
                    <LemonTag type="muted">Backfill</LemonTag>
                </Link>
            </Tooltip>
        </div>
    )
}
