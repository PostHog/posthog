import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { capitalizeFirstLetter } from 'lib/utils'

import { DatabaseSchemaQueryResponseField } from '~/queries/schema'
import { DataWarehouseViewLink, PropertyDefinition, PropertyType } from '~/types'

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
                    // valid join should have a joining table name
                    const table = externalTablesMap[join.joining_table_name as string]
                    return {
                        table,
                        join,
                    }
                })
            },
        ],
        columnsJoinedToPersons: [
            (s) => [s.tablesJoinedToPersons],
            (tablesJoinedToPersons) => {
                return tablesJoinedToPersons.reduce((acc, { table, join }) => {
                    if (table) {
                        acc.push(
                            ...table.columns.map((column: DatabaseSchemaQueryResponseField) => ({
                                id: column.key,
                                name: column.key,
                                table: join.field_name,
                                property_type: capitalizeFirstLetter(column.type) as PropertyType,
                            }))
                        )
                    }
                    return acc
                }, [] as PropertyDefinition[])
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadJoins()
    }),
])
