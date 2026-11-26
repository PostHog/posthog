import { urls } from 'scenes/urls'

import { InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { ActionType, ChartDisplayType } from '~/types'

/** A new trends insight that plots the action by day. */
export function actionTrendsInsightUrl(action: ActionType): string {
    const query: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: {
            kind: NodeKind.TrendsQuery,
            series: [
                {
                    id: action.id,
                    name: action.name || undefined,
                    kind: NodeKind.ActionsNode,
                },
            ],
            interval: 'day',
            trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
        },
    }
    return urls.insightNew({ query })
}
