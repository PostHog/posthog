import { IconArrowDown, IconArrowUp } from 'lib/lemon-ui/icons'

import type { ExperimentMetric } from '~/queries/schema/schema-general'
import { ExperimentMetricGoal } from '~/types'

export type MetricGoalProps = {
    metric: ExperimentMetric
}

export const MetricGoal = ({ metric }: MetricGoalProps): JSX.Element => {
    const goal = metric.goal || ExperimentMetricGoal.Increase
    const isIncrease = goal === ExperimentMetricGoal.Increase
    const Icon = isIncrease ? IconArrowUp : IconArrowDown

    return (
        <div className="flex items-center gap-1 text-xs">
            <span className="text-muted">Goal:</span>
            <Icon className="text-success flex-shrink-0" fontSize="16" />
            <span className="font-semibold">{isIncrease ? 'Increase' : 'Decrease'}</span>
        </div>
    )
}
