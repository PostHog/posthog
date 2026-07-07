import { useValues } from 'kea'

import { insightLogic } from 'scenes/insights/insightLogic'
import { ConfidenceLevelInput } from 'scenes/insights/views/LineGraph/ConfidenceLevelInput'
import { MovingAverageIntervalsInput } from 'scenes/insights/views/LineGraph/MovingAverageIntervalsInput'
import { trendsDataLogic } from 'scenes/trends/trendsDataLogic'

import { ConfidenceInterval, MovingAverage } from './DisplayOptions'

export function ConfidenceIntervalFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showConfidenceIntervals } = useValues(trendsDataLogic(insightProps))

    return (
        <div className="flex flex-col">
            <ConfidenceInterval />
            {showConfidenceIntervals && <ConfidenceLevelInput />}
        </div>
    )
}

export function MovingAverageFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { showMovingAverage } = useValues(trendsDataLogic(insightProps))

    return (
        <div className="flex flex-col">
            <MovingAverage />
            {showMovingAverage && <MovingAverageIntervalsInput />}
        </div>
    )
}
