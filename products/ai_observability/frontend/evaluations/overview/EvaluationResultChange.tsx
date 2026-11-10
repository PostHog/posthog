import { IconArrowRightDown, IconArrowUpRight } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import type { EvaluationResultApi } from '../../generated/api.schemas'

/** Why a row shows no change against the previous period. */
export function noChangeReason(row: EvaluationResultApi): string {
    return row.gradedCount === 0
        ? 'No graded results in this range.'
        : row.lowEvidence
          ? 'Too few graded results to compare.'
          : row.previousGradedCount
            ? 'Too few graded results in the previous period to compare.'
            : 'No results in the previous period.'
}

export function EvaluationResultChange({ row }: { row: EvaluationResultApi }): JSX.Element | null {
    const { change } = row
    if (!change) {
        return null
    }
    // A change is not good or bad on its own, so it stays neutral. The attention tags say when it is worse.
    const Icon = change.value > 0 ? IconArrowUpRight : change.value < 0 ? IconArrowRightDown : null
    const magnitude = Math.abs(change.value).toFixed(change.unit === 'points' ? 2 : 1)
    return (
        <Tooltip title="Change against the previous period of the same length.">
            <span className="inline-flex items-center gap-0.5 whitespace-nowrap">
                {Icon && <Icon className="text-secondary" />}
                <span>{`${magnitude} ${change.unit}`}</span>
                {change.subject && <span className="text-secondary">{` ${change.subject}`}</span>}
            </span>
        </Tooltip>
    )
}
