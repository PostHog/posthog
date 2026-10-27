import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { lastResultDay, resultEvidence, resultHeadline } from './evaluationOverviewDisplay'
import { EvaluationResultChange } from './EvaluationResultChange'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

export function EvaluationResultCell({ row }: { row: EvaluationResultApi }): JSX.Element {
    const { timezone } = useValues(evaluationsOverviewLogic)
    if (row.gradedCount === 0) {
        const day = lastResultDay(row, timezone)
        return <div className="text-secondary">{day ? `No results since ${day}` : 'No results in this range'}</div>
    }
    const content = (
        <div className={cn('min-w-0', row.lowEvidence && 'opacity-60')}>
            <div className="text-sm @3xl:text-base font-semibold">{resultHeadline(row)}</div>
            <div className="text-xs text-secondary">{resultEvidence(row)}</div>
            {/* The trend column hides on a narrow table, so the change shows here instead. */}
            <div className="text-xs mt-0.5 @min-[32.5rem]:hidden">
                <EvaluationResultChange row={row} />
            </div>
        </div>
    )
    return row.lowEvidence ? (
        <Tooltip title="Too few graded results to rely on, so this result can swing a lot.">{content}</Tooltip>
    ) : (
        content
    )
}
