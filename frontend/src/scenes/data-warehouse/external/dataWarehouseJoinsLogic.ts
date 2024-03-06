import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { capitalizeFirstLetter } from 'lib/utils'

import { DatabaseSchemaQueryResponseField } from '~/queries/schema'
import { DataWarehouseViewLink } from '~/types'

import type { dataWarehouseJoinsLogicType } from './dataWarehouseJoinsLogicType'
import { dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'

export const dataWarehouseJoinsLogic = kea<dataWarehouseJoinsLogicType>([
    path(['scenes', 'data-warehouse', 'external', 'dataWarehouseJoinsLogic']),
    connect(() => ({
        values: [dataWarehouseSceneLogic, ['externalTablesMap']],
    })),
    loaders({
        joins: [
            [] as DataWarehouseViewLink[],
            {
                loadJoins: async () => {
                    const joins = await api.dataWarehouseViewLinks.list()
                    return joins.results
                },
            },
        ],
    }),
    selectors({
        personTableJoins: [(s) => [s.joins], (joins) => joins.filter((join) => join.source_table_name === 'persons')],
        tablesJoinedToPersons: [
            (s) => [s.externalTablesMap, s.personTableJoins],
            (externalTablesMap, personTableJoins) => {
                return personTableJoins.map((join: DataWarehouseViewLink) => {
                    const table = externalTablesMap[join.joining_table_name]
                    return table
                })
            },
        ],
        columnsJoinedToPersons: [
            (s) => [s.tablesJoinedToPersons],
            (tablesJoinedToPersons) => {
                return tablesJoinedToPersons.reduce((acc, table) => {
                    if (table) {
                        acc.push(
                            ...table.columns.map((column) => ({
                                id: column.key,
                                name: column.key,
                                table: table.name,
                                property_type: capitalizeFirstLetter(column.type),
                            }))
                        )
                    }
                    return acc
                }, [] as DatabaseSchemaQueryResponseField[])
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadJoins()
    }),
])
