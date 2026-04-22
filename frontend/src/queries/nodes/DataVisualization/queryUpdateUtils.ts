import type { MutableRefObject } from 'react'

import { DataVisualizationNode } from '~/queries/schema/schema-general'

export const applyDataVisualizationQueryUpdate = (
    queryRef: MutableRefObject<DataVisualizationNode>,
    setter: (query: DataVisualizationNode) => DataVisualizationNode,
    setQuery: (query: DataVisualizationNode) => void
): void => {
    const nextQuery = setter(queryRef.current)
    queryRef.current = nextQuery
    setQuery(nextQuery)
}
