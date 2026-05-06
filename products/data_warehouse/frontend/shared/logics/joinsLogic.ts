import { afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { DatabaseSerializedFieldType } from '~/queries/schema/schema-general'
import { DataWarehouseViewLink, PropertyDefinition, PropertyType } from '~/types'

import type { joinsLogicType } from './joinsLogicType'

const TYPE_MAPPING: Partial<Record<DatabaseSerializedFieldType, PropertyType>> = {
    datetime: PropertyType.DateTime,
    string: PropertyType.String,
    integer: PropertyType.Numeric,
    float: PropertyType.Numeric,
    decimal: PropertyType.Numeric,
    boolean: PropertyType.Boolean,
    array: PropertyType.StringArray,
}

export const joinsLogic = kea<joinsLogicType>([
    path(['products', 'dataWarehouse', 'joinsLogic']),
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
        values: [databaseTableListLogic, ['allTablesMap']],
    })),
    selectors({
        personTableJoins: [(s) => [s.joins], (joins) => joins.filter((join) => join.source_table_name === 'persons')],
        tablesJoinedToPersons: [
            (s) => [s.allTablesMap, s.personTableJoins],
            (allTablesMap, personTableJoins) => {
                return personTableJoins.map((join: DataWarehouseViewLink) => {
                    // valid join should have a joining table name
                    const table = allTablesMap[join.joining_table_name as string]

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
                                id: `${join.field_name}.${column.name}`,
                                name: `${join.field_name}: ${column.name}`,
                                table: join.field_name,
                                property_type: TYPE_MAPPING[column.type] || PropertyType.String,
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
