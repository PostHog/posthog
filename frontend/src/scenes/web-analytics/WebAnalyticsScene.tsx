import { SceneExport } from 'scenes/sceneTypes'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'

export function WebAnalyticsScene(): JSX.Element {
    return (
        <div>
            Top sources
            <Query
                query={{
                    full: true,
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebTopSourcesQuery,
                        filters: {},
                    },
                }}
                readOnly={true}
            />
            Top clicks
            <Query
                query={{
                    full: true,
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebTopClicksQuery,
                        filters: {},
                    },
                }}
                readOnly={true}
            />
            Top pages
            <Query
                query={{
                    full: true,
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.WebTopPagesQuery,
                        filters: { x: 1 },
                    },
                }}
                readOnly={true}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: WebAnalyticsScene,
    logic: webAnalyticsLogic,
}
