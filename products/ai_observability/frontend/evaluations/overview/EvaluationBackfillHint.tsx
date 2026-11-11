import { useActions, useValues } from 'kea'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { type BackfillHintSource, evaluationResultDrawerLogic } from './evaluationResultDrawerLogic'
import { EvaluationRunOnPastDataButton } from './EvaluationRunOnPastDataButton'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

/** Offers a backfill for a chart line broken into single points by buckets without results. */
export function EvaluationBackfillHint({
    row,
    source,
    named = false,
}: {
    row: EvaluationResultApi
    source: BackfillHintSource
    named?: boolean
}): JSX.Element {
    const { interval } = useValues(evaluationsOverviewLogic)
    const { trackBackfillHint } = useActions(evaluationResultDrawerLogic)

    return (
        <div className="flex flex-wrap items-center gap-x-2 text-xs text-secondary">
            <span className="min-w-0 break-words">
                {named ? <strong className="text-primary">{row.name}</strong> : 'This evaluation'}
                {` has ${interval}s with no results, so some points have no line.`}
            </span>
            <EvaluationRunOnPastDataButton
                row={row}
                size="xsmall"
                type="tertiary"
                onClick={() => trackBackfillHint(source)}
                dataAttr="evaluation-overview-backfill-hint"
            />
        </div>
    )
}
