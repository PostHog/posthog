import { SceneExport } from 'scenes/sceneTypes'
import { webAnalyticsLogic } from 'scenes/web-analytics/webAnalyticsLogic'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'

export function WebAnalyticsScene(): JSX.Element {
    return (
        <div>
            Top pages
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
        </div>
    )
}

export const scene: SceneExport = {
    component: WebAnalyticsScene,
    logic: webAnalyticsLogic,
}
