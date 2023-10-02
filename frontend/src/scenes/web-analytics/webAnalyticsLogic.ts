import { actions, connect, kea, listeners, path, reducers, selectors, sharedListeners } from 'kea'

import type { webAnalyticsLogicType } from './webAnalyticsLogicType'
import { NodeKind, QuerySchema } from '~/queries/schema'
import { Layout } from 'react-grid-layout'
enum GridItems {
    overview = 'overview',
    top_pages = 'top_pages',
    top_sources = 'top_sources',
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
                        i: GridItems.overview,
                        x: 0,
                        y: 0,
                        w: 12,
                        h: 1,
                        static: true,
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
                        i: GridItems.top_pages,
                        x: 0,
                        y: 1,
                        w: 6,
                        h: 1,
                        static: true,
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
                        i: GridItems.top_sources,
                        x: 6,
                        y: 1,
                        w: 6,
                        h: 1,
                        static: true,
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
        layouts: [(s) => [s.tiles], (tiles) => ({ sm: tiles.map((t) => t.layout) })],
        gridRows: [() => [], () => 2],
    }),
    sharedListeners(() => ({})),
    listeners(() => ({})),
])
