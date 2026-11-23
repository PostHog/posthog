import type { DataWarehouseViewCreateInput, DataWarehouseViewCreateInputQuery } from '../generated/api.js'
import {
    type DefineIssue,
    type Definition,
    defineKind,
    dependenciesOf,
    isDefinition,
    issuesOf,
    withDependencies,
    withIssues,
} from './definition.js'
import { PROPERTY, type PropertyRef } from './event.js'

export type HogQLQueryNode = DataWarehouseViewCreateInputQuery

// The same escaping as PostHog's `escape_hogql_identifier` and string literals.
const ESCAPES: Readonly<Record<string, string>> = {
    '\b': '\\b',
    '\f': '\\f',
    '\r': '\\r',
    '\n': '\\n',
    '\t': '\\t',
    '\0': '\\0',
    '\x07': '\\a',
    '\v': '\\v',
    '\\': '\\\\',
}

export function hogqlString(value: string): string {
    return `'${[...value].map((char) => (char === "'" ? "\\'" : (ESCAPES[char] ?? char))).join('')}'`
}

export function hogqlIdentifier(name: string): string {
    if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name)) {
        return name
    }
    return `\`${[...name].map((char) => (char === '`' ? '``' : (ESCAPES[char] ?? char))).join('')}\``
}

// A fragment `sql` pastes as written, for SQL built in code.
export const RAW: unique symbol = Symbol.for('posthog.define.raw-sql')

export interface RawSql {
    readonly [RAW]: string
}

function isRaw(value: unknown): value is RawSql {
    return (
        typeof value === 'object' && value !== null && typeof (value as Record<PropertyKey, unknown>)[RAW] === 'string'
    )
}

function isPropertyRef(value: unknown): value is PropertyRef {
    return typeof value === 'object' && value !== null && PROPERTY in value
}

export type SqlValue =
    | string
    | number
    | boolean
    | null
    | Definition<'event'>
    | Definition<'model'>
    | PropertyRef
    | RawSql
    | HogQLQueryNode

// HogQL reads an event property as a string unless the project's property definition says
// otherwise, and a new event has no property definition yet. A property declared Numeric is read
// as a number, the way HogQL itself converts one with a definition.
const PROPERTY_READS: Readonly<Record<string, string>> = { Numeric: 'toFloat' }

function renderValue(value: SqlValue, issues: DefineIssue[], dependencies: Definition[]): string {
    if (isPropertyRef(value)) {
        const { event, name, declared, type } = value[PROPERTY]
        if (!declared) {
            issues.push({
                code: 'property_undeclared',
                message: `The query reads ${name} from the event ${event}, which doesn't declare it. Add it to the event's properties, or fix the name.`,
                path: 'query',
            })
        }
        const read = `properties.${hogqlIdentifier(name)}`
        const convert = type === undefined ? undefined : PROPERTY_READS[type]
        return convert ? `${convert}(${read})` : read
    }
    if (isRaw(value)) {
        return value[RAW]
    }
    if (isDefinition(value)) {
        if (value.kind === 'event') {
            return hogqlString(value.key)
        }
        if (value.kind === 'model') {
            // The query reads the model's table, so the model is created first. An event needs no
            // such order: the events table exists whether or not the event has a definition.
            dependencies.push(value)
            return hogqlIdentifier(value.key)
        }
        const other = value as Definition
        throw new TypeError(`sql can interpolate an event or a model, not the ${other.kind} ${other.key}.`)
    }
    if (typeof value === 'object' && value !== null && 'query' in value) {
        issues.push(...issuesOf(value))
        dependencies.push(...dependenciesOf(value))
        return value.query
    }
    if (typeof value === 'string') {
        return hogqlString(value)
    }
    if (value === null) {
        return 'NULL'
    }
    return String(value)
}

// A HogQL query. An event renders as its name in quotes, `event.props.x` as `properties.x` (read as a
// number when the property is declared Numeric), a model as its table name, a string as a quoted
// literal and `sql.raw(text)` as written.
//
// A query written indented inside the template loses the indentation and the blank first and last
// lines, so the SQL editor shows it flush left.
export function sql(strings: TemplateStringsArray, ...values: SqlValue[]): HogQLQueryNode {
    const issues: DefineIssue[] = []
    const dependencies: Definition[] = []
    let query = strings[0] ?? ''
    values.forEach((value, index) => {
        query += renderValue(value, issues, dependencies) + (strings[index + 1] ?? '')
    })
    return withDependencies(withIssues({ kind: 'HogQLQuery' as const, query: dedent(query) }, issues), dependencies)
}

function dedent(text: string): string {
    if (!text.startsWith('\n')) {
        return text
    }
    const lines = text
        .slice(1)
        .replace(/\n[ \t]*$/, '')
        .split('\n')
    const indent = Math.min(...lines.filter((line) => line.trim()).map((line) => line.length - line.trimStart().length))
    return lines.map((line) => line.slice(Number.isFinite(indent) ? indent : 0)).join('\n')
}

sql.raw = (text: string): RawSql => ({ [RAW]: text })

// The declared row shape of a model, so rows can be typed and columns checked.
export type ColumnType = 'string' | 'number' | 'integer' | 'boolean' | 'date' | 'datetime' | 'json'

export type Columns = Readonly<Record<string, ColumnType>>

interface ColumnValue {
    string: string
    number: number
    integer: number
    boolean: boolean
    date: string
    datetime: string
    json: unknown
}

export type RowOf<C extends Columns> = { [Name in keyof C]: ColumnValue[C[Name]] }

type SyncFrequency = NonNullable<DataWarehouseViewCreateInput['sync_frequency']>

export interface ModelBody extends Omit<
    DataWarehouseViewCreateInput,
    'name' | 'query' | 'folder_id' | 'acknowledge_breaking_changes' | 'is_test'
> {
    name: string
    query: HogQLQueryNode
    is_materialized?: boolean
    columns: Record<string, ColumnType>
}

export interface ModelInput<C extends Columns> extends Omit<ModelBody, 'name' | 'query' | 'columns'> {
    // `sql` or `file('./x.sql')`.
    query: HogQLQueryNode | string
    columns: C
    // Materializes the model on this schedule: `is_materialized` plus `sync_frequency`.
    materialize?: Exclude<SyncFrequency, 'never'>
}

export interface ModelExtra<C extends Columns> {
    readonly columns: C
}

export type ModelDefinition<Name extends string = string, C extends Columns = Columns> = Definition<
    'model',
    Name,
    ModelBody
> &
    ModelExtra<C>

export type RowsOf<M> = M extends ModelExtra<infer C> ? RowOf<C>[] : never

export function model<const Name extends string, const C extends Columns>(
    name: Name,
    input: ModelInput<C>
): ModelDefinition<Name, C> {
    const { query, columns, materialize, ...fields } = input
    const node = typeof query === 'string' ? { kind: 'HogQLQuery' as const, query } : query
    const body: ModelBody = {
        ...fields,
        name,
        query: node,
        ...(materialize !== undefined ? { is_materialized: true, sync_frequency: materialize } : {}),
        columns: { ...columns },
    }
    return defineKind('model', name, body, {}, { columns })
}

// A column check shared by the builders that name a model's columns.
export function columnIssues(
    target: ModelDefinition,
    names: readonly (string | undefined)[],
    path: string
): DefineIssue[] {
    return names
        .filter((name): name is string => name !== undefined && !(name in target.columns))
        .map((name) => ({
            code: 'column_undeclared',
            message: `The model ${target.key} declares no column ${name}. Add it to the model's columns, or fix the name.`,
            path,
        }))
}
