import { BuiltLogic, useActions, useValues } from 'kea'
import { useLayoutEffect } from 'react'

import { dataNodeLogicType } from './dataNodeLogic'

export function QueryJourneyCommit({
    logic,
    response,
    ready,
}: {
    logic: BuiltLogic<dataNodeLogicType>
    response: unknown
    ready: boolean
}): null {
    const { queryJourneyReceipt } = useValues(logic)
    const { acknowledgeQueryJourney } = useActions(logic)
    useLayoutEffect(() => {
        if (ready && queryJourneyReceipt && queryJourneyReceipt.response === response) {
            acknowledgeQueryJourney(queryJourneyReceipt.generation, response)
        }
    }, [ready, queryJourneyReceipt, response, acknowledgeQueryJourney])
    return null
}
