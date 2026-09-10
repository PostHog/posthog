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

    it('offers a joined column as a dotted path and drops the join placeholder', () => {
        const columns = dataWarehouseColumnsWithJoins(['ad_stats'], tablesMap)

        expect(columns.map((column) => column.name)).toEqual([
            'campaign_id',
            'impressions',
            'campaign.id',
            'campaign.name',
        ])
    })

    it('keeps a table without joins unchanged and tolerates an unknown joined table', () => {
        expect(dataWarehouseColumnsWithJoins(['unknown_table'], tablesMap)).toEqual([])
        expect(
            dataWarehouseColumnsWithJoins(['orders'], {
                orders: table('orders', [field('total', 'integer'), field('customer', 'lazy_table', 'missing')]),
            }).map((column) => column.name)
        ).toEqual(['total'])
    })
})
