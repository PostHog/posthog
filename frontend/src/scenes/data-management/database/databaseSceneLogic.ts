import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { query } from '~/queries/query'

import type { databaseSceneLogicType } from './databaseSceneLogicType'
import { NodeKind } from '~/queries/schema'

export const databaseSceneLogic = kea<databaseSceneLogicType>([
    path(['scenes', 'data-management', 'database', 'databaseSceneLogic']),
    loaders({
        database: [
            null as any,
            {
                loadDatabase: () => query({ kind: NodeKind.DatabaseSchemaQuery }),
            },
        ],
    }),
    afterMount(({ actions }) => actions.loadDatabase()),
])
