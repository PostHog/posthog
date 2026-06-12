import { useValues } from 'kea'

import { insightVizDataLogic } from '@posthog/query-frontend/nodes/InsightViz/insightVizDataLogic'
import { insightVizDataNodeKey } from '@posthog/query-frontend/nodes/InsightViz/insightVizKeys'
import { Query } from '@posthog/query-frontend/Query/Query'
import { DataTableNode, InsightVizNode, NodeKind } from '@posthog/query-frontend/schema/schema-general'
import { QueryContext } from '@posthog/query-frontend/types'
import { isWebOverviewQuery, isWebStatsTableQuery } from '@posthog/query-frontend/utils'

import { insightLogic } from '../insights/insightLogic'
import { webAnalyticsDataTableQueryContext } from './tiles/WebAnalyticsTile'

export interface WebAnalyticsInsightProps {
    context?: QueryContext<InsightVizNode>
    editMode?: boolean
}

export function WebAnalyticsInsight({ context, editMode }: WebAnalyticsInsightProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource } = useValues(insightVizDataLogic(insightProps))

    // Use the same dataNodeLogic key as InsightViz so we reuse the existing logic
    // instance with its cached data instead of creating a new one
    const vizKey = insightVizDataNodeKey(insightProps)

    if (isWebStatsTableQuery(querySource)) {
        // Wrap WebStatsTableQuery in DataTableNode with the same structure as Web Analytics uses
        // Hide the cross_sell column to remove cross-sell buttons in Product Analytics
        const wrappedQuery: DataTableNode = {
            kind: NodeKind.DataTableNode,
            source: querySource,
            full: true,
            showActions: false,
            embedded: false,
            hiddenColumns: ['context.columns.cross_sell'],
        }

        // Use the Web Analytics query context for custom column rendering and formatting
        // Pass compareFilter so VariationCell can access it when webAnalyticsLogic is not mounted
        const webAnalyticsContext: QueryContext = {
            ...context,
            ...webAnalyticsDataTableQueryContext,
            compareFilter: querySource.compareFilter,
        } as QueryContext

        return <Query query={wrappedQuery} uniqueKey={vizKey} context={webAnalyticsContext} readOnly={!editMode} />
    } else if (isWebOverviewQuery(querySource)) {
        return <Query query={querySource} uniqueKey={vizKey} context={context} readOnly={!editMode} />
    }

    return null
}
