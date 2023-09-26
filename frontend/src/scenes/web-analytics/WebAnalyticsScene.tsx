import { SceneExport } from 'scenes/sceneTypes'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { Query } from '~/queries/Query/Query'
import { DataTableNode, NodeKind } from '~/queries/schema'

export function WebAnalyticsScene(): JSX.Element {
    const query: DataTableNode = {
        full: true,
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.WebTopSourcesQuery,
            query: {},
        },
    }

    return (
        <div>
            Top pages
            <Query query={query} readOnly={true} />
        </div>
    )
}

export const scene: SceneExport = {
    component: WebAnalyticsScene,
    logic: webAnalyticsLogic,
}
