import { kea, path, selectors } from 'kea'

import { NodeKind } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { EmbeddedAnalyticsTileId, EmbeddedQueryTile } from './common'
import type { embeddedAnalyticsLogicType } from './embeddedAnalyticsLogicType'

export const embeddedAnalyticsLogic = kea<embeddedAnalyticsLogicType>([
    path(['scenes', 'embedded-analytics', 'embeddedAnalyticsLogic']),

    selectors({
        tiles: [
            () => [],
            (): EmbeddedQueryTile[] => [
                {
                    kind: 'query',
                    tileId: EmbeddedAnalyticsTileId.API_QUERIES_COUNT,
                    title: 'API Queries Count',
                    layout: {
                        colSpanClassName: 'md:col-span-6',
                    },
                    query: {
                        kind: NodeKind.DataVisualizationNode,
                        source: {
                            kind: NodeKind.HogQLQuery,
                            query: `select 
                                        event_date, 
                                        count(1) as number_of_queries
                                    from query_log
                                    where 
                                        is_personal_api_key_request and 
                                        event_date >= today() - interval 21 day
                                    group by event_date
                                    order by event_date asc`,
                        },
                    },
                    insightProps: {
                        dashboardItemId: 'embedded_analytics_api_queries',
                        cachedInsight: null,
                    } as InsightLogicProps,
                    canOpenInsight: false,
                    canOpenModal: false,
                },
            ],
        ],
    }),
])
