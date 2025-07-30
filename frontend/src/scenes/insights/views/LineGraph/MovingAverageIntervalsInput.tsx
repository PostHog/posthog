import { LemonInput, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { isTrendsQuery } from '~/queries/utils'
import { useDebouncedCallback } from 'use-debounce'
import { useState, useEffect } from 'react'

export function MovingAverageIntervalsInput(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { movingAverageIntervals, showMovingAverage } = useValues(trendsDataLogic(insightProps))
    const { querySource } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const trendsFilter = isTrendsQuery(querySource) ? querySource.trendsFilter : undefined

    const [localValue, setLocalValue] = useState(movingAverageIntervals)

    useEffect(() => {
        setLocalValue(movingAverageIntervals)
    }, [movingAverageIntervals])

    const debouncedUpdate = useDebouncedCallback((value: number) => {
        if (isTrendsQuery(querySource)) {
            const newQuery = { ...querySource }
            newQuery.trendsFilter = { ...trendsFilter, movingAverageIntervals: value }
            updateQuerySource(newQuery)
        }
    }, 500)

    return (
        <div className="flex items-center justify-between w-full px-2 pb-2 pl-4">
            <Tooltip title="The number of data points to use for calculating the moving average. A larger number will create a smoother line but with more lag.">
                <span>Intervals</span>
            </Tooltip>
            <LemonInput
                type="number"
                className="w-20"
                value={localValue}
                onChange={(value) => {
                    const numValue = value ?? 7
                    setLocalValue(numValue)
                    debouncedUpdate(numValue)
                }}
                min={1}
                step={1}
                disabledReason={!showMovingAverage ? 'Moving averages are only available for line graphs' : undefined}
            />
        </div>
    )
}
