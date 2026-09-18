import { BuiltLogic, useActions } from 'kea'
import { useLayoutEffect } from 'react'

import { dataNodeLogicType } from './dataNodeLogic'

export function QueryJourneySurface({ logic }: { logic: BuiltLogic<dataNodeLogicType> }): null {
    const { observeQueryJourney, stopObservingQueryJourney } = useActions(logic)
    useLayoutEffect(() => {
        const owner = Symbol()
        observeQueryJourney(owner)
        return () => stopObservingQueryJourney(owner)
    }, [logic, observeQueryJourney, stopObservingQueryJourney])
    return null
}
