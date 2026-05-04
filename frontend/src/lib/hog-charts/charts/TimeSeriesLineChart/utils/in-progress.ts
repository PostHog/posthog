import type { Series } from '../../../core/types'

export interface InProgressConfig {
    fromIndex: number
}

export function applyInProgressToSeries<Meta = unknown>(
    series: Series<Meta>[],
    inProgress: InProgressConfig | undefined
): Series<Meta>[] {
    if (inProgress?.fromIndex === undefined) {
        return series
    }
    const fromIndex = inProgress.fromIndex
    return series.map((s) =>
        s.stroke?.partial !== undefined ? s : { ...s, stroke: { ...s.stroke, partial: { fromIndex } } }
    )
}
