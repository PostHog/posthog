import { DataWarehouseTableForInsight } from 'products/data_warehouse/frontend/types'

import { getDataWarehouseItemWithFieldDefaults } from './dataWarehouseItemUtils'

describe('getDataWarehouseItemWithFieldDefaults', () => {
    type WarehouseFields = DataWarehouseTableForInsight['fields']
    type FieldDefaultCase = {
        name: string
        fields: WarehouseFields
        expected: string
    }

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

    const distinctIdCases: FieldDefaultCase[] = [
        {
            name: 'prefers distinct_id when multiple distinct ID candidates are present',
            fields: {
                ...baseTable.fields,
                distinct_id: { name: 'distinct_id', hogql_value: 'distinct_id', type: 'string', schema_valid: true },
                email: { name: 'email', hogql_value: 'email', type: 'string', schema_valid: true },
            },
            expected: 'distinct_id',
        },
        {
            name: 'falls back to email when distinct_id is not present',
            fields: {
                ...baseTable.fields,
                email: { name: 'email', hogql_value: 'email', type: 'string', schema_valid: true },
            },
            expected: 'email',
        },
        {
            name: 'matches distinct ID candidates case-insensitively',
            fields: {
                ...baseTable.fields,
                user_uuid: { name: 'User_ID', hogql_value: 'User_ID', type: 'string', schema_valid: true },
            },
            expected: 'User_ID',
        },
    ]

    it.each(distinctIdCases)('$name', ({ fields, expected }) => {
        const warehouseItem = getDataWarehouseItemWithFieldDefaults({
            ...baseTable,
            fields,
        })

        expect(warehouseItem.distinct_id_field).toEqual(expected)
    })

    const timestampCases: FieldDefaultCase[] = [
        {
            name: 'prefers a named timestamp candidate over another datetime column',
            fields: {
                id: { name: 'id', hogql_value: 'id', type: 'integer', schema_valid: true },
                happened_at: { name: 'happened_at', hogql_value: 'happened_at', type: 'datetime', schema_valid: true },
                updated_at: { name: 'updated_at', hogql_value: 'updated_at', type: 'datetime', schema_valid: true },
            },
            expected: 'updated_at',
        },
        {
            name: 'falls back to the first datetime or date field when no timestamp candidate exists',
            fields: {
                id: { name: 'id', hogql_value: 'id', type: 'integer', schema_valid: true },
                happened_at: { name: 'happened_at', hogql_value: 'happened_at', type: 'datetime', schema_valid: true },
                event_date: { name: 'event_date', hogql_value: 'event_date', type: 'date', schema_valid: true },
            },
            expected: 'happened_at',
        },
        {
            name: 'matches timestamp candidates case-insensitively',
            fields: {
                id: { name: 'id', hogql_value: 'id', type: 'integer', schema_valid: true },
                createdAt: { name: 'CreatedAt', hogql_value: 'CreatedAt', type: 'string', schema_valid: true },
            },
            expected: 'CreatedAt',
        },
    ]

    it.each(timestampCases)('$name', ({ fields, expected }) => {
        const warehouseItem = getDataWarehouseItemWithFieldDefaults({
            ...baseTable,
            fields,
        })

        expect(warehouseItem.timestamp_field).toEqual(expected)
    })
})
