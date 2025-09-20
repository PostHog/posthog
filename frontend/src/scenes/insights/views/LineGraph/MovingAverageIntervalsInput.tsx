import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { LemonInput, Tooltip } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { INTERVAL_TO_DEFAULT_MOVING_AVERAGE_PERIOD, trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { isTrendsQuery } from '~/queries/utils'

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

    const interval = isTrendsQuery(querySource) ? querySource.interval || 'day' : 'day'

    return (
        <Tooltip title="The number of data points to use for calculating the moving average. A larger number will create a smoother line but with more lag. You can't use a number greater than the amount of intervals in your date range.">
            <div className="flex items-center justify-between w-full px-2 pb-2 pl-4 gap-1">
                <span>Intervals</span>

                <LemonInput
                    type="number"
                    className="w-30"
                    value={localValue}
                    onChange={(value) => {
                        const numValue = value ?? INTERVAL_TO_DEFAULT_MOVING_AVERAGE_PERIOD[interval]
                        setLocalValue(numValue)
                        debouncedUpdate(numValue)
                    }}
                    min={2}
                    suffix={<span>{`${interval}s`}</span>}
                    step={1}
                    disabledReason={
                        !showMovingAverage ? 'Moving averages are only available for line graphs' : undefined
                    }
                />
            </div>
        </Tooltip>
    )
}
