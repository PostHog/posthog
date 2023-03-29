import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { query } from '~/queries/query'

import type { databaseSceneLogicType } from './databaseSceneLogicType'
import { DatabaseSchemaQuery, DatabaseSchemaQueryResponseField, NodeKind } from '~/queries/schema'
import api from 'lib/api'
import { DataBeachTableType } from '~/types'

export interface DataBeachTable {
    name: string
    engine: string
    dataBeachTableId?: number
    columns: DatabaseSchemaQueryResponseField[]
}

export const databaseSceneLogic = kea<databaseSceneLogicType>([
    path(['scenes', 'data-management', 'database', 'databaseSceneLogic']),
    actions({
        showAddDataBeachTable: true,
        hideAddDataBeachTable: true,
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        appendDataBeachTable: (dataBeachTable: DataBeachTableType) => ({ dataBeachTable }),
    }),
    loaders({
        database: [
            null as Required<DatabaseSchemaQuery['response']> | null,
            {
                loadDatabase: async (): Promise<Required<DatabaseSchemaQuery['response']> | null> =>
                    await query({ kind: NodeKind.DatabaseSchemaQuery } as DatabaseSchemaQuery),
            },
        ],
        dataBeachTables: [
            null as DataBeachTableType[] | null,
            {
                loadDataBeachTables: async () => (await api.dataBeachTables.list())?.results,
            },
        ],
    }),
    reducers({
        addingDataBeachTable: [false, { showAddDataBeachTable: () => true, hideAddDataBeachTable: () => false }],
        searchTerm: ['', { setSearchTerm: (_, { searchTerm }) => searchTerm }],
        dataBeachTables: { appendDataBeachTable: (state, { dataBeachTable }) => [...(state ?? []), dataBeachTable] },
    }),
    selectors({
        loading: [
            (s) => [s.databaseLoading, s.dataBeachTablesLoading],
            (databaseLoading, dataBeachTablesLoading) => databaseLoading || dataBeachTablesLoading,
        ],
        filteredTables: [
            (s) => [s.database, s.dataBeachTables, s.searchTerm],
            (database, dataBeachTables, searchTerm): DataBeachTable[] => {
                if (!database) {
                    return []
                }
                const dataBeachTablesByName: Record<string, DataBeachTableType> = {}
                for (const dataBeachTable of dataBeachTables ?? []) {
                    dataBeachTablesByName[dataBeachTable.name] = dataBeachTable
                }

                let filteredTables: DataBeachTable[] = Object.entries(database).map(
                    ([key, value]) =>
                        ({
                            name: key,
                            columns: value,
                            engine: dataBeachTablesByName[key]?.engine,
                            dataBeachTableId: dataBeachTablesByName[key]?.id,
                        } as DataBeachTable)
                )
                for (const table of dataBeachTables ?? []) {
                    if (!database[table.name]) {
                        filteredTables.push({
                            name: table.name,
                            columns: table.fields.map((column) => ({
                                key: column.name,
                                type: column.type,
                            })),
                            engine: table.engine,
                            dataBeachTableId: table.id,
                        })
                    }
                }
                if (searchTerm) {
                    filteredTables = filteredTables.filter(({ name }) =>
                        name.toLowerCase().includes(searchTerm.toLowerCase())
                    )
                }
                filteredTables.sort((a, b) => a.name.localeCompare(b.name))
                return filteredTables
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadDatabase()
        actions.loadDataBeachTables()
    }),
])
