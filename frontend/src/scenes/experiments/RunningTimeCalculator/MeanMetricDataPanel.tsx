import type { ExperimentMetric } from '~/queries/schema/schema-general'

import {
    AverageEventsPerUserPanel,
    AveragePropertyValuePerUserPanel,
    StandardDeviationPanel,
    UniqueUsersPanel,
} from './components'
import { calculateVariance } from './experimentStatisticsUtils'

type MeanMetricDataPanelProps = {
    metric: ExperimentMetric
    uniqueUsers: number
    averageEventsPerUser: number
    averagePropertyValuePerUser: number
}

export const MeanMetricDataPanel = ({
    metric,
    uniqueUsers,
    averageEventsPerUser,
    averagePropertyValuePerUser,
}: MeanMetricDataPanelProps): JSX.Element => {
    const variance = calculateVariance(metric, averageEventsPerUser, averagePropertyValuePerUser)

    const standardDeviation = variance ? Math.sqrt(variance) : null

    return (
        <div className="grid grid-cols-3 gap-4">
            <UniqueUsersPanel uniqueUsers={uniqueUsers ?? 0} />
            <AverageEventsPerUserPanel averageEventsPerUser={averageEventsPerUser} />
            <AveragePropertyValuePerUserPanel averagePropertyValuePerUser={averagePropertyValuePerUser} />
            <StandardDeviationPanel standardDeviation={standardDeviation} />
        </div>
    )
}
