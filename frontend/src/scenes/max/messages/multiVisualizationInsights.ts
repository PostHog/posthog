import { useMemo } from 'react'

import { VisualizationItem } from '~/queries/schema/schema-assistant-messages'
import { DataVisualizationNode, InsightVizNode } from '~/queries/schema/schema-general'

import { visualizationTypeToQuery } from '../utils'

export interface MultiVisualizationInsight {
    query: InsightVizNode | DataVisualizationNode
    title: string
}

export function useMultiVisualizationInsights(visualizations: VisualizationItem[]): MultiVisualizationInsight[] {
    return useMemo(
        () =>
            visualizations.flatMap((visualization, index) => {
                const query = visualizationTypeToQuery(visualization)
                // Visualization items only ever carry insight or data-visualization queries.
                const insightQuery = query as InsightVizNode | DataVisualizationNode | null
                return insightQuery
                    ? [{ query: insightQuery, title: visualization.plan || `Insight #${index + 1}` }]
                    : []
            }),
        [visualizations]
    )
}
