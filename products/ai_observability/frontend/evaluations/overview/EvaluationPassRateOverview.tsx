import { useValues } from 'kea'
import { useMemo } from 'react'

import { useChartTheme } from 'lib/charts/hooks'

import { EvaluationChartEmptyState } from './EvaluationChartEmptyState'
import { EvaluationCompareList } from './EvaluationCompareList'
import { EvaluationPassRateCompareChart } from './EvaluationPassRateCompareChart'
import { evaluationsOverviewLogic } from './evaluationsOverviewLogic'

export function EvaluationPassRateOverview(): JSX.Element {
    const theme = useChartTheme()
    const { chartedIds, nothingGraded, rows } = useValues(evaluationsOverviewLogic)
    const colors = useMemo(() => {
        const palette = theme.colors.slice(1)
        return new Map(chartedIds.map((id, index) => [id, palette[index % palette.length]]))
    }, [chartedIds, theme])

    // With nothing graded the layout stays the same: the list shows why each one is empty, the chart what fills it.
    return (
        <div className="flex flex-col gap-4 min-w-0 @3xl:flex-row">
            <div className="@3xl:w-72 shrink-0">
                <EvaluationCompareList colors={colors} />
            </div>
            <div className="flex-1 min-w-0 flex flex-col gap-2">
                {nothingGraded ? (
                    <EvaluationChartEmptyState pausedRows={rows.filter((row) => !row.enabled)} />
                ) : (
                    <EvaluationPassRateCompareChart colors={colors} />
                )}
            </div>
        </div>
    )
}
