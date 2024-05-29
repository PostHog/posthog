import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { capitalizeFirstLetter } from 'lib/utils'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { DataWarehouseViewLink, PropertyDefinition, PropertyType } from '~/types'

import type { dataWarehouseJoinsLogicType } from './dataWarehouseJoinsLogicType'

export const dataWarehouseJoinsLogic = kea<dataWarehouseJoinsLogicType>([
    path(['scenes', 'data-warehouse', 'external', 'dataWarehouseJoinsLogic']),
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
    connect(() => ({
        values: [databaseTableListLogic, ['dataWarehouseTablesMap']],
    })),
    selectors({
        personTableJoins: [(s) => [s.joins], (joins) => joins.filter((join) => join.source_table_name === 'persons')],
        tablesJoinedToPersons: [
            (s) => [s.dataWarehouseTablesMap, s.personTableJoins],
            (dataWarehouseTablesMap, personTableJoins) => {
                return personTableJoins.map((join: DataWarehouseViewLink) => {
                    // valid join should have a joining table name
                    const table = dataWarehouseTablesMap[join.joining_table_name as string]
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
                            ...Object.values(table.fields).map((column) => ({
                                id: join.field_name + ': ' + column.name,
                                name: join.field_name + ': ' + column.name,
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
