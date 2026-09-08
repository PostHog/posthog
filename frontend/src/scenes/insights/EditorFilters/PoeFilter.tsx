import { useActions, useValues } from 'kea'

import { LemonDisabledArea, LemonLabel, LemonSwitch } from '@posthog/lemon-ui'

import { InsightLogicProps } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'
import { poeFilterLogic } from './poeFilterLogic'

interface PoeFilterProps {
    insightProps: InsightLogicProps
}

export function PoeFilter({ insightProps }: PoeFilterProps): JSX.Element {
    const { queryTimePoeEnabled } = useValues(poeFilterLogic(insightProps))
    const { hasDataWarehouseSeries } = useValues(insightVizDataLogic(insightProps))
    const { setQueryTimePoeEnabled } = useActions(poeFilterLogic(insightProps))
    const disabledReason = hasDataWarehouseSeries
        ? 'Data warehouse insights always use the latest table properties.'
        : undefined

    return (
        <LemonDisabledArea className="flex items-center gap-1 w-fit" disabledReason={disabledReason}>
            <LemonLabel
                info="Overrides the default person property mode for this insight to use query-time person properties instead of event-time properties. This can be useful when person data is updated after the event, but it can also slow queries significantly."
                infoLink="https://posthog.com/docs/how-posthog-works/queries#filtering-on-person-properties"
            >
                Use person properties from query time
            </LemonLabel>
            <LemonSwitch
                className="m-2"
                disabled={!!disabledReason}
                onChange={setQueryTimePoeEnabled}
                checked={queryTimePoeEnabled}
            />
        </LemonDisabledArea>
    )
}
