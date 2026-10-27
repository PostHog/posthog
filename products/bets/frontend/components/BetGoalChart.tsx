import { useCallback } from 'react'

import type { BetsDetailApi } from '../generated/api.schemas'
import { chartTicks } from '../lib/chartTicks'
import { metricPeriod, number } from '../lib/format'
import { BetMiniChart } from './BetMiniChart'

export function BetGoalChart({
    bet,
}: {
    bet: Pick<BetsDetailApi, 'target' | 'unit' | 'goal_metric' | 'metric'>
}): JSX.Element {
    const target = bet.target === null ? null : Number(bet.target)
    const formatValue = useCallback((value: number) => number(value, bet.unit), [bet.unit])
    const formatLabel = useCallback((label: string) => metricPeriod([label]), [])
    return (
        <BetMiniChart
            label={bet.goal_metric}
            labels={bet.metric.dates}
            values={bet.metric.values}
            limit={target}
            limitLabel={target === null ? '' : `Target ${number(target, bet.unit)}`}
            formatValue={formatValue}
            formatLabel={formatLabel}
            empty={bet.metric.values.length ? undefined : 'No observations yet'}
            ticks={chartTicks(bet.metric.dates, (date) => metricPeriod([date]))}
        />
    )
}
