import { useValues } from 'kea'

import { experimentLogic } from '../experimentLogic'
import {
    AverageEventsPerUserPanel,
    AveragePropertyValuePerUserPanel,
    StandardDeviationPanel,
    UniqueUsersPanel,
} from './components'
import { runningTimeCalculatorLogic } from './runningTimeCalculatorLogic'

export const MeanMetricDataPanel = (): JSX.Element => {
    const { experiment } = useValues(experimentLogic)
    const { uniqueUsers, averageEventsPerUser, averagePropertyValuePerUser, standardDeviation } = useValues(
        runningTimeCalculatorLogic({ experiment })
    )

    return (
        <div className="grid grid-cols-3 gap-4">
            <UniqueUsersPanel uniqueUsers={uniqueUsers ?? 0} />
            <AverageEventsPerUserPanel averageEventsPerUser={averageEventsPerUser} />
            <AveragePropertyValuePerUserPanel averagePropertyValuePerUser={averagePropertyValuePerUser} />
            <StandardDeviationPanel standardDeviation={standardDeviation} />
        </div>
    )
}
