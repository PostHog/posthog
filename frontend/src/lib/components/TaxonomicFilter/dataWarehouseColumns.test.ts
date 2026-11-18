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
            const columns = dataWarehouseColumnsWithJoins(['ad_stats'], tablesMap, { includeJoinedColumns })

            expect(columns.map((column) => column.name)).toEqual(expected)
        }
    )

    it('resolves a connector-synced join target through its printed, backquoted name', () => {
        const columns = dataWarehouseColumnsWithJoins(
            ['ad_spend'],
            {
                ad_spend: table('ad_spend', [
                    field('spend', 'integer'),
                    field('campaign', 'lazy_table', '`stripe.campaigns`'),
                ]),
                'stripe.campaigns': table('stripe.campaigns', [field('title', 'string')]),
            },
            { includeJoinedColumns: true }
        )

        expect(columns.map((column) => column.name)).toEqual(['spend', 'campaign.title'])
    })

    it('drops a table-valued traverser on the joined table', () => {
        const columns = dataWarehouseColumnsWithJoins(
            ['ad_spend'],
            {
                ad_spend: table('ad_spend', [field('spend', 'integer'), field('evt', 'lazy_table', 'events')]),
                events: table('events', [field('event', 'string'), field('person', 'field_traverser')]),
            },
            { includeJoinedColumns: true }
        )

        expect(columns.map((column) => column.name)).toEqual(['spend', 'evt.event'])
    })

    it('keeps a table without joins unchanged and tolerates an unknown joined table', () => {
        expect(dataWarehouseColumnsWithJoins(['unknown_table'], tablesMap, { includeJoinedColumns: true })).toEqual([])
        expect(
            dataWarehouseColumnsWithJoins(
                ['orders'],
                {
                    orders: table('orders', [field('total', 'integer'), field('customer', 'lazy_table', 'missing')]),
                },
                { includeJoinedColumns: true }
            ).map((column) => column.name)
        ).toEqual(['total'])
    })

    it.each([
        [false, ['id', 'country']],
        [true, ['id', 'country', 'campaign.name']],
    ])(
        'offers only the columns every table shares when an insight spans several (includeJoinedColumns=%s)',
        (includeJoinedColumns, expected) => {
            const columns = dataWarehouseColumnsWithJoins(
                ['orders', 'refunds'],
                {
                    orders: table('orders', [
                        field('id', 'string'),
                        field('country', 'string'),
                        field('amount', 'integer'),
                        field('campaign', 'lazy_table', 'campaigns'),
                    ]),
                    refunds: table('refunds', [
                        field('id', 'string'),
                        field('country', 'string'),
                        field('reason', 'string'),
                        field('campaign', 'lazy_table', 'campaigns'),
                    ]),
                    campaigns: table('campaigns', [field('name', 'string')]),
                },
                { includeJoinedColumns }
            )

            expect(columns.map((column) => column.name)).toEqual(expected)
        }
    )
})
