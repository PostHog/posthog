import { useValues } from 'kea'
import { useState } from 'react'

import { AnyResponseType, CoreWebVitalsPathBreakdownQuery } from '~/queries/schema'
import { QueryContext } from '~/queries/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'

let uniqueNode = 0
export function CoreWebVitalsPathBreakdown(props: {
    query: CoreWebVitalsPathBreakdownQuery
    cachedResults?: AnyResponseType
    context: QueryContext
}): JSX.Element | null {
    const { onData, loadPriority, dataNodeCollectionId } = props.context.insightProps ?? {}
    const [key] = useState(() => `CoreWebVitalsPathBreakdown.${uniqueNode++}`)

    const logic = dataNodeLogic({
        query: props.query,
        key,
        cachedResults: props.cachedResults,
        loadPriority,
        onData,
        dataNodeCollectionId: dataNodeCollectionId ?? key,
    })

    const { response, responseLoading } = useValues(logic)

    return <div>CoreWebVitalsPathBreakdown - {JSON.stringify([response, responseLoading])}</div>
}
