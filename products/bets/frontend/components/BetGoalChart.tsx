import { useCallback, useMemo, useState } from 'react'

import type { BetsDetailApi } from '../generated/api.schemas'
import { chartTicks } from '../lib/chartTicks'
import { metricPeriod, number } from '../lib/format'
import { type BetIdeaPin, BetIdeaPins, pinRowHeight } from './BetIdeaPins'
import { BetMiniChart } from './BetMiniChart'

const RESULT_PLOT = 112
const AXIS_ROW = 20

export function BetGoalChart({
    bet,
    pins,
}: {
    bet: Pick<BetsDetailApi, 'target' | 'unit' | 'goal_metric' | 'metric'>
    pins?: BetIdeaPin[]
}): JSX.Element {
    const [levels, setLevels] = useState(1)
    const target = bet.target === null ? null : Number(bet.target)
    const formatValue = useCallback((value: number) => number(value, bet.unit), [bet.unit])
    const formatLabel = useCallback((label: string) => metricPeriod([label]), [])
    const top = pins?.length ? pinRowHeight(Math.max(1, levels)) + 6 : 10
    const edge = useMemo(
        () => (pins ? { top, height: top + RESULT_PLOT + AXIS_ROW, avoid: pins.map((pin) => pin.at) } : undefined),
        [pins, top]
    )
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
            edge={edge}
        >
            {pins?.length ? <BetIdeaPins pins={pins} onLevels={setLevels} /> : null}
        </BetMiniChart>
    )
}
