import { useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'
import { Query } from '~/queries/Query/Query'
import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema'
import { BaseMathType } from '~/types'

export const scene: SceneExport = {
    component: PlaygroundScene,
}

const trendsDefaultQuery: TrendsQuery = {
    kind: NodeKind.TrendsQuery,
    series: [
        {
            kind: NodeKind.EventsNode,
            name: '$pageview',
            event: '$pageview',
            math: BaseMathType.TotalCount,
        },
    ],
    trendsFilter: {},
}

function PlaygroundScene(): JSX.Element {
    const initialQuery: InsightVizNode = {
        kind: NodeKind.InsightVizNode,
        source: trendsDefaultQuery,
        full: true,
        showFilters: true,
    }
    const [query, setQuery] = useState(initialQuery)
    return (
        <div>
            <h1>Playground</h1>
            <pre>{JSON.stringify(query, null, 2)}</pre>
            <Query query={query} setQuery={setQuery} readOnly={false} />
        </div>
    )
}
