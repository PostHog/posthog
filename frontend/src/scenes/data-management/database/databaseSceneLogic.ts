import { actions, afterMount, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { query } from '~/queries/query'

import type { databaseSceneLogicType } from './databaseSceneLogicType'
import { NodeKind } from '~/queries/schema'
import api from 'lib/api'
import { DataBeachTableType } from '~/types'

export const databaseSceneLogic = kea<databaseSceneLogicType>([
    path(['scenes', 'data-management', 'database', 'databaseSceneLogic']),
    actions({
        showAddDataBeachTable: true,
        hideAddDataBeachTable: true,
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
    }),
    reducers({
        addingDataBeachTable: [false, { showAddDataBeachTable: () => true, hideAddDataBeachTable: () => false }],
        searchTerm: ['', { setSearchTerm: (_, { searchTerm }) => searchTerm }],
    }),
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
                loadDataBeachTables: async () => (await api.dataBeachTables.list())?.results,
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadDatabase()
        actions.loadDataBeachTables()
    }),
])
