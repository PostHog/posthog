import { DataWarehouseTableForInsight } from 'scenes/data-warehouse/types'

import { getDataWarehouseItemWithFieldDefaults } from './dataWarehouseItemUtils'

describe('getDataWarehouseItemWithFieldDefaults', () => {
    const baseTable: DataWarehouseTableForInsight = {
        id: 'warehouse-table-id',
        name: 'warehouse_table',
        type: 'data_warehouse',
        format: 'Parquet',
        url_pattern: '',
        fields: {
            id: { name: 'id', hogql_value: 'id', type: 'integer', schema_valid: true },
            created_at: { name: 'created_at', hogql_value: 'created_at', type: 'datetime', schema_valid: true },
        },
    }

    it('prefers person_distinct_ids.person_id from joined fields for aggregation target defaults', () => {
        const warehouseItem = getDataWarehouseItemWithFieldDefaults({
            ...baseTable,
            fields: {
                ...baseTable.fields,
                person_id: { name: 'person_id', hogql_value: 'person_id', type: 'string', schema_valid: true },
                person_distinct_ids: {
                    name: 'person_distinct_ids',
                    hogql_value: 'person_distinct_ids',
                    type: 'lazy_table',
                    schema_valid: true,
                    table: 'person_distinct_ids',
                    fields: ['distinct_id', 'person_id'],
                },
            },
        })

        expect(warehouseItem.aggregation_target_field).toEqual('person_distinct_ids.person_id')
    })

    it('falls back to a top-level person_id column when no matching join is present', () => {
        const warehouseItem = getDataWarehouseItemWithFieldDefaults({
            ...baseTable,
            fields: {
                ...baseTable.fields,
                person_id: { name: 'person_id', hogql_value: 'person_id', type: 'string', schema_valid: true },
            },
        })

        expect(warehouseItem.aggregation_target_field).toEqual('person_id')
    })
})
