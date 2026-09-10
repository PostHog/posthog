import { DatabaseSchemaField, DatabaseSchemaTable } from '~/queries/schema/schema-general'

import { dataWarehouseColumnsWithJoins } from './dataWarehouseColumns'

const field = (name: string, type: DatabaseSchemaField['type'], table?: string): DatabaseSchemaField => ({
    name,
    hogql_value: name,
    type,
    schema_valid: true,
    ...(table ? { table } : {}),
})

const table = (name: string, fields: DatabaseSchemaField[]): DatabaseSchemaTable =>
    ({
        name,
        type: 'data_warehouse',
        id: name,
        fields: Object.fromEntries(fields.map((f) => [f.name, f])),
    }) as DatabaseSchemaTable

describe('dataWarehouseColumnsWithJoins', () => {
    const tablesMap: Record<string, DatabaseSchemaTable> = {
        ad_stats: table('ad_stats', [
            field('campaign_id', 'string'),
            field('impressions', 'integer'),
            field('campaign', 'lazy_table', 'campaigns'),
        ]),
        campaigns: table('campaigns', [
            field('id', 'string'),
            field('name', 'string'),
            field('stats', 'lazy_table', 'ad_stats'),
        ]),
    }

    it.each([
        [true, ['campaign_id', 'impressions', 'campaign.id', 'campaign.name']],
        [false, ['campaign_id', 'impressions']],
    ])(
        'always drops the join placeholder and emits dotted joined columns only when asked (includeJoinedColumns=%s)',
        (includeJoinedColumns, expected) => {
            const columns = dataWarehouseColumnsWithJoins(['ad_stats'], tablesMap, includeJoinedColumns)

            expect(columns.map((column) => column.name)).toEqual(expected)
        }
    )

    it('keeps a table without joins unchanged and tolerates an unknown joined table', () => {
        expect(dataWarehouseColumnsWithJoins(['unknown_table'], tablesMap, true)).toEqual([])
        expect(
            dataWarehouseColumnsWithJoins(
                ['orders'],
                {
                    orders: table('orders', [field('total', 'integer'), field('customer', 'lazy_table', 'missing')]),
                },
                true
            ).map((column) => column.name)
        ).toEqual(['total'])
    })
})
