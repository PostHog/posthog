import { useCallback, useMemo } from 'react'

import { dayjs } from 'lib/dayjs'

import type { BetsDetailApi } from '../generated/api.schemas'
import { chartTicks } from '../lib/chartTicks'
import { money } from '../lib/format'
import { BetMiniChart } from './BetMiniChart'

export function BetSpendChart({ bet }: { bet: Pick<BetsDetailApi, 'spend_history' | 'money'> }): JSX.Element {
    const history = bet.spend_history
    const labels = useMemo(() => history.map((point) => point.at), [history])
    const values = useMemo(() => history.map((point) => point.spent_cents), [history])
    const sameDay = labels.length > 1 && dayjs(labels[0]).isSame(labels[labels.length - 1], 'day')
    const formatLabel = useCallback((label: string) => dayjs(label).format('MMM D, h:mm A'), [])
    const ticks = useMemo(
        () => chartTicks(labels, (label) => dayjs(label).format(sameDay ? 'h:mm A' : 'MMM D')),
        [labels, sameDay]
    )
    return (
        <BetMiniChart
            label="Spent"
            labels={labels}
            values={values}
            limit={bet.money.allocated_cents}
            limitLabel={`Budget ${money(bet.money.allocated_cents)}`}
            formatValue={money}
            formatLabel={formatLabel}
            floor={0}
            empty={history.length ? undefined : 'No usage yet'}
            ticks={ticks}
        />
    )
}
