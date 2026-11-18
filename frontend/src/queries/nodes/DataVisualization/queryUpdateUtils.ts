import type { MutableRefObject } from 'react'

import { NodeKind, VisualizationNode } from '~/queries/schema/schema-general'

export const applyDataVisualizationQueryUpdate = (
    queryRef: MutableRefObject<VisualizationNode>,
    setter: (query: VisualizationNode) => VisualizationNode,
    setQuery: (query: VisualizationNode) => void
): void => {
    const updated = setter(queryRef.current)
    const nextQuery =
        updated.kind === NodeKind.BIVisualizationNode && updated.display
            ? { ...updated, config: { ...updated.config, chartType: updated.display } }
            : updated
    queryRef.current = nextQuery
    setQuery(nextQuery)
}
