import { actions, connect, kea, listeners, path, reducers, selectors, sharedListeners } from 'kea'

import type { webAnalyticsLogicType } from './webAnalyticsLogicType'
import { NodeKind, QuerySchema } from '~/queries/schema'

interface Layout {
    colSpan?: number
    rowSpan?: number
}
export interface WebDashboardTile {
    query: QuerySchema
    layout: Layout
}
export const webAnalyticsLogic = kea<webAnalyticsLogicType>([
    path(['scenes', 'webAnalytics', 'webAnalyticsSceneLogic']),
    connect({}),
    actions({}),
    reducers({}),
    selectors({
        tiles: [
            () => [],
            (): WebDashboardTile[] => [
                {
                    layout: {
                        colSpan: 12,
                    },
                    query: {
                        full: true,
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: NodeKind.WebOverviewStatsQuery,
                            filters: {},
                        },
                    },
                },
                {
                    layout: {
                        colSpan: 6,
                    },
                    query: {
                        full: true,
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: NodeKind.WebTopPagesQuery,
                            filters: {},
                        },
                    },
                },
                {
                    layout: {
                        colSpan: 6,
                    },
                    query: {
                        full: true,
                        kind: NodeKind.DataTableNode,
                        source: {
                            kind: NodeKind.WebTopSourcesQuery,
                            filters: {},
                        },
                    },
                },
            ],
        ],
    }),
    sharedListeners(() => ({})),
    listeners(() => ({})),
])
