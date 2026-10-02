import {
    BIDataSource,
    BIField,
    buildBIQuery,
    DEFAULT_BI_CONFIG,
    getBIDropTarget,
} from 'scenes/data-warehouse/editor/bi/biEditorTypes'

import { DatabaseSchemaField, DatabaseSchemaTable } from '~/queries/schema/schema-general'

import { buildBIConnections } from './biConnectionTree'

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

it('drags nested dimensions and measures using paths from the original source', () => {
    const [person] = buildBIConnections(source, tables, ['["person"]', '["person","company"]'], {}, true)
    const [company] = person.connections
    expect(company.connections).toEqual([])
    const dimension = company.fields.dimensions[0]
    const measure = company.fields.measures[0]
    expect(dimension).toMatchObject({ name: 'person.company.name', expression: 'person.company.name', source })
    expect(measure).toMatchObject({ name: 'person.company.annual_revenue', type: 'decimal', source })
    const value = getBIDropTarget(measure, 'rows').field as BIField
    const query = buildBIQuery({
        ...DEFAULT_BI_CONFIG,
        source,
        rows: [dimension],
        values: [{ field: value, aggregation: 'sum' }],
    })
    expect(query?.query).toContain('person.company.name')
    expect(query?.query).toContain('sum(person.company.annual_revenue)')
    expect(query?.query).toContain('FROM events')
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
] as const)('distinguishes unresolved, failed, and empty connections (%s, complete=%s)', (status, complete, state) => {
    const catalog = { ...tables, persons: table('persons', []) }
    const [person] = buildBIConnections(source, catalog, ['["person"]'], status ? { persons: status } : {}, complete)
    expect(person.state).toBe(state)
    expect(person.fields).toEqual({ dimensions: [], measures: [] })
})

it('does not recurse forever when aliases refer to each other', () => {
    const catalog = {
        events: table('events', [
            field('first', 'field_traverser', { chain: ['second'] }),
            field('second', 'field_traverser', { chain: ['first'] }),
        ]),
    }
    expect(buildBIConnections(source, catalog, [], {}, true)).toEqual([])
})
