import { LemonDivider, LemonTag } from '@posthog/lemon-ui'
import { PageHeader } from 'lib/components/PageHeader'
import { SceneExport } from 'scenes/sceneTypes'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { ChartDisplayType, InsightType } from '~/types'

export const Issues = (): JSX.Element => {
    return (
        <div>
            <PageHeader
                title={
                    <div className="flex items-center gap-2">
                        Issues
                        <LemonTag type="warning" className="uppercase">
                            BETA
                        </LemonTag>
                    </div>
                }
                buttons={undefined}
            />

            <LemonDivider />
            <Query
                query={{
                    kind: NodeKind.LegacyQuery,
                    filters: {
                        insight: InsightType.TRENDS,
                        date_from: '-7d',
                        events: [
                            {
                                id: '$pageview',
                                math: 'avg_count_per_actor',
                                name: '$pageview',
                                type: 'events',
                                order: 0,
                            },
                        ],
                        display: ChartDisplayType.ActionsLineGraph,
                        interval: 'day',
                    },
                }}
            />
            <LemonDivider />
            <Query
                query={{
                    kind: NodeKind.DataTableNode,
                    full: true,
                    showOpenEditorButton: false,
                    source: {
                        kind: NodeKind.EventsQuery,
                        select: ['*', 'person', 'timestamp'],
                        properties: [],
                        fixedProperties: [
                            // todo fix by defined user event/action
                        ],
                        after: '-24h',
                        limit: 100,
                    },
                }}
            />
        </div>
    )
}

export const scene: SceneExport = {
    component: Issues,
}
