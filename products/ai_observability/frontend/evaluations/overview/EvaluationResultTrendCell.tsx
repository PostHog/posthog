import { Tooltip } from '@posthog/lemon-ui'

import type { EvaluationResultApi } from '../../generated/api.schemas'
import { EvaluationResultChange, noChangeReason } from './EvaluationResultChange'
import { EvaluationResultMiniChart } from './EvaluationResultMiniChart'

export function EvaluationResultTrendCell({
    row,
    buckets,
}: {
    row: EvaluationResultApi
    buckets: string[]
}): JSX.Element | null {
    if (row.gradedCount === 0) {
        return null
    }
    return (
        <div className="w-32 @3xl:w-44 flex flex-col gap-1">
            {row.change && (
                <div className="text-xs">
                    <EvaluationResultChange row={row} />
                </div>
            )}
            {/* Without a change line, the chart carries the reason there is none. */}
            <Tooltip title={row.change ? undefined : noChangeReason(row)}>
                <div>
                    <EvaluationResultMiniChart row={row} buckets={buckets} />
                </div>
            </Tooltip>
        </div>
    )
}
