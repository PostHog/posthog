import { useValues } from 'kea'

import { Query } from '~/queries/Query/Query'
import { DataTableNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { isWebOverviewQuery, isWebStatsTableQuery } from '~/queries/utils'

import { insightLogic } from '../insights/insightLogic'
import { insightVizDataLogic } from '../insights/insightVizDataLogic'
import { webAnalyticsDataTableQueryContext } from './tiles/WebAnalyticsTile'

export interface WebAnalyticsInsightProps {
    context?: QueryContext<InsightVizNode>
    editMode?: boolean
}

export function WebAnalyticsInsight({ context, editMode }: WebAnalyticsInsightProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { querySource } = useValues(insightVizDataLogic(insightProps))

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

        return <Query query={wrappedQuery} context={webAnalyticsContext} readOnly={!editMode} />
    } else if (isWebOverviewQuery(querySource)) {
        return <Query query={querySource} context={context} readOnly={!editMode} />
    }

    return null
}
