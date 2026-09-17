import { useActions, useValues } from 'kea'

import { LemonDisabledArea, LemonLabel, LemonSwitch } from '@posthog/lemon-ui'

import { InsightLogicProps } from '~/types'

import { insightVizDataLogic } from '../insightVizDataLogic'
import { poeFilterLogic } from './poeFilterLogic'

interface PoeFilterProps {
    insightProps: InsightLogicProps
}

export function PoeFilter({ insightProps }: PoeFilterProps): JSX.Element {
    const { poeMode } = useValues(poeFilterLogic(insightProps))
    const { hasDataWarehouseSeries } = useValues(insightVizDataLogic(insightProps))
    const { setPoeMode } = useActions(poeFilterLogic(insightProps))
    const disabledReason = hasDataWarehouseSeries
        ? 'Data warehouse insights always use the latest table properties.'
        : undefined

    return (
        <LemonDisabledArea className="flex items-center gap-1 w-fit" disabledReason={disabledReason}>
            <LemonLabel
                info="This insight matches person properties as they were when each event happened. Turn this on to match the current values instead. Use it when a person property changed after the event, for example an internal user filter that you set up recently and that does not exclude older events. Query-time person properties can slow the insight down a lot."
                infoLink="https://posthog.com/docs/how-posthog-works/queries#filtering-on-person-properties"
            >
                Use person properties from query time
            </LemonLabel>
            <LemonSwitch
                className="m-2"
                disabled={!!disabledReason}
                onChange={(checked) => {
                    if (checked) {
                        setPoeMode('person_id_override_properties_joined')
                    } else {
                        setPoeMode(null)
                    }
                }}
                checked={!!poeMode}
            />
        </LemonDisabledArea>
    )
}
