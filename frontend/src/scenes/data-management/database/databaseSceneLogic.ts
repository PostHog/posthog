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
        editDataBeachTable: (id: number | 'new' = 'new') => ({ id }),
        hideEditDataBeachTable: true,
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        appendDataBeachTable: (dataBeachTable: DataBeachTableType) => ({ dataBeachTable }),
        updateDataBeachTable: (dataBeachTable: DataBeachTableType) => ({ dataBeachTable }),
        setCategory: (category: 'all' | 'posthog' | 'databeach') => ({ category }),
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
        editingDataBeachTable: [
            null as 'new' | number | null,
            { editDataBeachTable: (_, { id }) => id, hideEditDataBeachTable: () => null },
        ],
        searchTerm: ['', { setSearchTerm: (_, { searchTerm }) => searchTerm }],
        dataBeachTables: {
            appendDataBeachTable: (state, { dataBeachTable }) => [...(state ?? []), dataBeachTable],
            updateDataBeachTable: (state, { dataBeachTable }) =>
                (state ?? []).map((table) => (table.id === dataBeachTable.id ? dataBeachTable : table)),
        },
        category: ['all' as 'all' | 'posthog' | 'databeach', { setCategory: (_, { category }) => category }],
    }),
    selectors({
        loading: [
            (s) => [s.databaseLoading, s.dataBeachTablesLoading],
            (databaseLoading, dataBeachTablesLoading) => databaseLoading || dataBeachTablesLoading,
        ],
        filteredTables: [
            (s) => [s.database, s.dataBeachTables, s.searchTerm, s.category],
            (database, dataBeachTables, searchTerm, category): DataBeachTable[] => {
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
                if (category === 'posthog') {
                    filteredTables = filteredTables.filter((table) => table.dataBeachTableId === undefined)
                }
                if (category === 'databeach') {
                    filteredTables = filteredTables.filter((table) => table.dataBeachTableId !== undefined)
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
        editingDataBeachTableObject: [
            (s) => [s.dataBeachTables, s.editingDataBeachTable],
            (dataBeachTables, editingDataBeachTable) =>
                editingDataBeachTable ? dataBeachTables.find(({ id }) => id === editingDataBeachTable) : null,
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadDatabase()
        actions.loadDataBeachTables()
    }),
])
