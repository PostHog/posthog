import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import { query } from '~/queries/query'

import type { databaseSceneLogicType } from './databaseSceneLogicType'
import { NodeKind } from '~/queries/schema'
import api from 'lib/api'
import { DataBeachTableType } from '~/types'

export const databaseSceneLogic = kea<databaseSceneLogicType>([
    path(['scenes', 'data-management', 'database', 'databaseSceneLogic']),
    loaders({
        database: [
            null as any,
            {
                loadDatabase: () => query({ kind: NodeKind.DatabaseSchemaQuery }),
            },
        ],
        dataBeachTables: [
            null as DataBeachTableType[] | null,
            {
                loadDataBeachTables: () => api.dataBeachTables.list(),
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadDatabase()
        actions.loadDataBeachTables()
    }),
])
