import type { EvaluationResultApi } from '../../generated/api.schemas'
import { EvaluationResultChange } from './EvaluationResultChange'
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
            <div className="text-xs">
                <EvaluationResultChange row={row} />
            </div>
            <EvaluationResultMiniChart row={row} buckets={buckets} />
        </div>
    )
}
