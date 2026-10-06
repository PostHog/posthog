import { BIDataSource, BIField } from '~/queries/schema/schema-business-intelligence'
import { DatabaseSchemaField, DatabaseSchemaTable } from '~/queries/schema/schema-general'

import {
    buildBIConnections,
    filterBIConnections,
    getPendingBIConnectionTables,
} from 'products/business_intelligence/frontend/biConnectionTree'
import { buildBIQuery, DEFAULT_BI_CONFIG, getBIDropTarget } from 'products/business_intelligence/frontend/biEditorTypes'

const field = (
    name: string,
    type: DatabaseSchemaField['type'],
    rest: Partial<DatabaseSchemaField> = {}
): DatabaseSchemaField => ({ name, type, hogql_value: name, schema_valid: true, ...rest })
const table = (name: string, fields: DatabaseSchemaField[]): DatabaseSchemaTable => ({
    id: name,
    name,
    type: 'posthog',
    fields: Object.fromEntries(fields.map((field) => [field.name, field])),
})
const source: BIDataSource = { table: 'events', connectionId: 'example-connection' }
const tables = {
    events: table('events', [field('person', 'lazy_table', { table: 'persons' })]),
    persons: table('persons', [
        field('email', 'string'),
        field('lifetime_value', 'float'),
        field('company', 'lazy_table', { table: 'companies' }),
    ]),
    companies: table('companies', [field('name', 'string'), field('annual_revenue', 'decimal')]),
}

describe('BI connections', () => {
    it.each([
        ['events', 'person'],
        ['stripe_charges', 'customer'],
    ])('drags related dimensions and measures from %s through %s', (rootTable, relation) => {
        const rootSource = { ...source, table: rootTable }
        const warehouse = rootTable === 'stripe_charges'
        const relatedTable = warehouse ? 'stripe_customers' : 'persons'
        const catalog: Record<string, DatabaseSchemaTable> = {
            ...tables,
            [rootTable]: {
                ...table(rootTable, [
                    field(relation, 'lazy_table', {
                        table: `\`${relatedTable}\``,
                        fields: ['email', 'lifetime_value', 'company'],
                    }),
                ]),
                type: warehouse ? 'data_warehouse' : 'posthog',
            },
            [relatedTable]: {
                ...tables.persons,
                name: relatedTable,
                id: warehouse ? 'warehouse-customer-id' : 'persons',
                type: warehouse ? 'data_warehouse' : 'posthog',
            },
        }
        const [related] = buildBIConnections(
            rootSource,
            catalog,
            [JSON.stringify([relation]), JSON.stringify([relation, 'company'])],
            {},
            true
        )
        const [company] = related.connections
        expect(related.tableName).toBe(relatedTable)
        expect(company.connections).toEqual([])
        const dimension = company.fields.dimensions[0]
        const measure = company.fields.measures[0]
        expect(dimension).toMatchObject({
            name: `${relation}.company.name`,
            expression: `${relation}.company.name`,
            source: rootSource,
        })
        expect(measure).toMatchObject({
            name: `${relation}.company.annual_revenue`,
            type: 'decimal',
            source: rootSource,
        })
        const value = getBIDropTarget(measure, 'rows').field as BIField
        const query = buildBIQuery({
            ...DEFAULT_BI_CONFIG,
            source: rootSource,
            rows: [dimension],
            values: [{ field: value, aggregation: 'sum' }],
        })
        expect(query?.query).toContain(`${relation}.company.name`)
        expect(query?.query).toContain(`sum(${relation}.company.annual_revenue)`)
        expect(query?.query).toContain(`FROM ${rootTable}`)
    })

    it.each(['lazy_table', 'view', 'materialized_view', 'virtual_table'] as const)(
        'uses declared fields for %s connections',
        (type) => {
            const catalog = {
                ...tables,
                events: table('events', [field('person', type, { table: 'persons', fields: ['email'] })]),
            }
            const [person] = buildBIConnections(source, catalog, ['["person"]'], {}, true)
            expect(person.fields.dimensions.map((field) => field.name)).toEqual(['person.email'])
            expect(person.fields.measures).toEqual([])
            expect(person.connections).toEqual([])
        }
    )

    it('uses the PostHog table ID for hydration and status', () => {
        const catalog = { ...tables, persons: { ...table('persons', []), id: 'person-table-id' } }
        const expanded = ['["person"]']
        expect(getPendingBIConnectionTables(buildBIConnections(source, catalog, expanded, {}, false))).toEqual([
            'person-table-id',
        ])
        expect(buildBIConnections(source, catalog, expanded, { 'person-table-id': 'error' }, false)[0].state).toBe(
            'error'
        )
    })

    it('resolves linked aliases and only expands requested paths through cyclic tables', () => {
        const catalog = {
            ...tables,
            events: table('events', [
                field('person', 'lazy_table', { table: 'persons' }),
                field('customer', 'field_traverser', { chain: ['person'] }),
            ]),
            persons: table('persons', [field('email', 'string'), field('manager', 'lazy_table', { table: 'persons' })]),
        }
        const [customer] = buildBIConnections(source, catalog, ['["customer"]', '["customer","manager"]'], {}, true)
        expect(customer.fields.dimensions[0].expression).toBe('customer.email')
        const [manager] = customer.connections
        expect(manager.fields.dimensions[0].expression).toBe('customer.manager.email')
        expect(manager.connections[0]).toMatchObject({ expanded: false, connections: [] })
    })

    it.each([
        [undefined, false, 'loading'],
        ['error', false, 'error'],
        ['missing', false, 'missing'],
        ['loaded', false, 'ready'],
        [undefined, true, 'ready'],
    ] as const)(
        'distinguishes unresolved, failed, and empty connections (%s, complete=%s)',
        (status, complete, state) => {
            const catalog = { ...tables, persons: table('persons', []) }
            const [person] = buildBIConnections(
                source,
                catalog,
                ['["person"]'],
                status ? { persons: status } : {},
                complete
            )
            expect(person.state).toBe(state)
            expect(person.fields).toEqual({ dimensions: [], measures: [] })
        }
    )

    it('does not recurse forever when aliases refer to each other', () => {
        const catalog = {
            events: table('events', [
                field('first', 'field_traverser', { chain: ['second'] }),
                field('second', 'field_traverser', { chain: ['first'] }),
            ]),
        }
        expect(buildBIConnections(source, catalog, [], {}, true)).toEqual([])
    })

    it('lists virtual fields without borrowing types or connections from the printed parent table', () => {
        const catalog = {
            events: table('events', [
                field('id', 'integer'),
                field('created_at', 'lazy_table', { table: 'companies' }),
                field('person', 'field_traverser', { chain: ['poe'] }),
                field('poe', 'virtual_table', {
                    table: 'events',
                    fields: ['id', 'created_at', 'properties', 'team_id'],
                }),
            ]),
        }
        const person = buildBIConnections(source, catalog, ['["person"]'], { events: 'error' }, false).find(
            (c) => c.name === 'person'
        )!
        expect(person).toMatchObject({ state: 'ready', tableName: undefined, connections: [] })
        expect(person.fields.dimensions).toEqual([
            expect.objectContaining({ name: 'person.created_at', type: 'unknown', source }),
            expect.objectContaining({ name: 'person.id', type: 'unknown', source }),
            expect.objectContaining({ name: 'person.properties', type: 'unknown', source }),
        ])
        expect(person.fields.measures).toEqual([])
        expect(getPendingBIConnectionTables([person])).toEqual([])
    })

    it.each([undefined, 'error'] as const)(
        'keeps unresolved aliases visible and searchable while intermediate fields are %s',
        (status) => {
            const catalog = {
                events: table('events', [
                    field('person', 'field_traverser', { chain: ['pdi', 'person'] }),
                    field('pdi', 'lazy_table', { table: 'person_distinct_ids' }),
                ]),
                person_distinct_ids: table('person_distinct_ids', []),
            }
            const connections = buildBIConnections(
                source,
                catalog,
                ['["person"]'],
                status ? { person_distinct_ids: status } : {},
                false
            )
            const person = filterBIConnections(connections, 'email').find((c) => c.name === 'person')!
            expect(person).toMatchObject({ state: status ?? 'loading', tableName: 'person_distinct_ids' })
            expect(getPendingBIConnectionTables(connections)).toEqual(status ? [] : ['person_distinct_ids'])
        }
    )
})
