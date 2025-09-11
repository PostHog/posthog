import { actions, afterMount, kea, path, props, propsChanged } from 'kea'
import { loaders } from 'kea-loaders'

import { performQuery } from '~/queries/query'
import {
    InsightActorsQuery,
    InsightActorsQueryOptions,
    InsightActorsQueryOptionsResponse,
    NodeKind,
} from '~/queries/schema/schema-general'
import { isInsightActorsQuery, setLatestVersionsOnQuery } from '~/queries/utils'

import type { insightActorsQueryOptionsLogicType } from './insightActorsQueryOptionsLogicType'

export const insightActorsQueryOptionsLogic = kea<insightActorsQueryOptionsLogicType>([
    path(['queries', 'nodes', 'DataTable', 'sourceQueryOptionsLogic']),
    props({} as { key: string; query: InsightActorsQuery }),
    actions({
        load: true,
    }),
    loaders(({ values, props }) => ({
        insightActorsQueryOptions: [
            null as InsightActorsQueryOptionsResponse | null,
            {
                load: async () => {
                    if (!props.query || !isInsightActorsQuery(props.query)) {
                        return values.insightActorsQueryOptions || null
                    }
                    const optionsQuery: InsightActorsQueryOptions = setLatestVersionsOnQuery(
                        {
                            kind: NodeKind.InsightActorsQueryOptions,
                            source: props.query,
                        },
                        { recursion: false }
                    )
                    return await performQuery(optionsQuery)
                },
            },
        ],
    })),
    afterMount(({ actions }) => {
        actions.load()
    }),
    propsChanged(({ actions, props }, oldProps) => {
        if (JSON.stringify(props.query) !== JSON.stringify(oldProps.query)) {
            actions.load()
        }
    }),
])
