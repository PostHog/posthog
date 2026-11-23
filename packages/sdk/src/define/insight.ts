import type {
    ProductAnalyticsInsightCreateInput,
    ProductAnalyticsInsightCreateInputQuery,
    QueriesFunnelInput,
    QueriesTrendsInput,
} from '../generated/api.js'
import type { JsonValue } from '../types.js'
import {
    type Definition,
    defineKind,
    dependenciesOf,
    isDefinition,
    issuesOf,
    type RefTo,
    withDependencies,
    withIssues,
} from './definition.js'
import type { EventDefinition, PropSpec, PropSpecs } from './event.js'
import { type Columns, columnIssues, hogqlIdentifier, type HogQLQueryNode, type ModelDefinition } from './model.js'

type GeneratedQuery = ProductAnalyticsInsightCreateInputQuery
type GeneratedVizNode = Extract<GeneratedQuery, { kind?: 'InsightVizNode' }>

// Query shapes PostHog stores and runs that the generated create input lacks. Each one matches a
// named schema gap in the stack registry, so the types and `check` accept the same bodies.
interface VizNodeWithHeader extends GeneratedVizNode {
    showHeader?: boolean
    embedded?: boolean
    full?: boolean
    hidePersonsModal?: boolean
    hideTooltipOnScroll?: boolean
    showCorrelationTable?: boolean
    showFilters?: boolean
    showLastComputation?: boolean
    showLastComputationRefresh?: boolean
    showResults?: boolean
    showTable?: boolean
    suppressSessionAnalysisWarning?: boolean
    version?: number
}

interface SqlDataTable {
    kind: 'DataTableNode'
    source: { kind: 'HogQLQuery'; query: string; [field: string]: JsonValue }
    [field: string]: JsonValue
}

export type InsightQuery = Exclude<GeneratedQuery, GeneratedVizNode> | VizNodeWithHeader | SqlDataTable

// The create body, with each dashboard id replaced by the dashboard's definition. A dashboard adds
// itself here for every insight on its tiles, so this lists only dashboards that show the insight
// without a tile layout, and, by id, dashboards outside the stack.
export interface InsightInput extends Omit<ProductAnalyticsInsightCreateInput, 'dashboards' | 'query'> {
    query: InsightQuery
    dashboards?: readonly (RefTo<'dashboard'> | number)[]
    // The name PostHog shows for an insight without one. The API takes it as written.
    derived_name?: string | null
    // Set on an insight adopted from PostHog. The API takes it as written.
    deleted?: boolean
}

export type InsightDefinition<Key extends string = string> = Definition<'insight', Key, InsightInput>

export function insight<const Key extends string>(key: Key, body: InsightInput): InsightDefinition<Key> {
    return defineKind('insight', key, body)
}

// What every builder takes besides its query.
export type InsightFields = Omit<InsightInput, 'query'>

function withFields(fields: InsightFields, query: InsightQuery): InsightInput {
    return { ...fields, query }
}

type DataVisualizationNode = Extract<GeneratedQuery, { kind?: 'DataVisualizationNode' }>

export interface HogQLInsightOptions extends InsightFields {
    // The HogQL (SQL) query the insight runs, as text or from `sql`.
    query: string | HogQLQueryNode
    display?: DataVisualizationNode['display']
    chartSettings?: DataVisualizationNode['chartSettings']
    tableSettings?: DataVisualizationNode['tableSettings']
}

// An SQL insight: a `DataVisualizationNode` over a `HogQLQuery`.
export function hogql({ query, display, chartSettings, tableSettings, ...fields }: HogQLInsightOptions): InsightInput {
    const text = typeof query === 'string' ? query : query.query
    // A query from `sql` keeps what it found, such as the models it reads.
    const source = { kind: 'HogQLQuery' as const, query: text }
    if (typeof query !== 'string') {
        withDependencies(withIssues(source, issuesOf(query)), dependenciesOf(query))
    }
    return withFields(fields, {
        kind: 'DataVisualizationNode',
        source,
        ...(display !== undefined ? { display } : {}),
        ...(chartSettings !== undefined ? { chartSettings } : {}),
        ...(tableSettings !== undefined ? { tableSettings } : {}),
    })
}

// The query wrappers' own inputs: the same schema `check` validates the source with.
type TrendsSource = Omit<QueriesTrendsInput, 'kind' | 'output_format'>
type FunnelsSource = Omit<QueriesFunnelInput, 'kind' | 'output_format'>

export type TrendSeries = TrendsSource['series'][number]
type EventsSeries = Extract<TrendSeries, { kind?: 'EventsNode' }>
export type FunnelStep = FunnelsSource['series'][number]

export interface TrendOptions extends TrendsSource, InsightFields {}

export interface FunnelOptions extends Omit<FunnelsSource, 'series'>, InsightFields {
    // The funnel's steps in order: the query's series.
    steps: FunnelsSource['series']
}

const FIELD_NAMES: ReadonlySet<string> = new Set(['name', 'description', 'tags', 'favorited', 'dashboards'])

function split(options: object): { fields: InsightFields; node: Record<string, JsonValue> } {
    const fields: Record<string, unknown> = {}
    const node: Record<string, JsonValue> = {}
    for (const [name, value] of Object.entries(options)) {
        if (value === undefined) {
            continue
        }
        if (FIELD_NAMES.has(name)) {
            fields[name] = value
        } else {
            node[name] = value as JsonValue
        }
    }
    return { fields: fields as InsightFields, node }
}

// A series without a kind is an `EventsNode`, as the query schema defaults it.
function seriesNodes(series: readonly object[]): JsonValue[] {
    return series.map((node) => ({ kind: 'EventsNode', ...node }) as JsonValue)
}

// The kind goes last, so nothing in the options can change which query this is.
function vizNode(kind: string, node: Record<string, JsonValue>): InsightQuery {
    return { kind: 'InsightVizNode', source: { ...node, kind } }
}

type WhereOf<Props extends PropSpecs> = {
    readonly [Name in keyof Props]?: Props[Name] extends PropSpec<infer Value>
        ? Value extends Date
            ? never
            : Value
        : never
}

export interface EventTrendOptions<Props extends PropSpecs> extends Omit<TrendOptions, 'series'> {
    // Exact matches on the event's own properties.
    where?: WhereOf<Props>
    math?: TrendSeries['math']
}

export interface ModelTrendOptions<C extends Columns> extends InsightFields {
    sum?: keyof C & string
    avg?: keyof C & string
    min?: keyof C & string
    max?: keyof C & string
    // The date or time column the trend buckets by. Defaults to the model's first date or datetime column.
    timestamp?: keyof C & string
    interval?: 'hour' | 'day' | 'week' | 'month'
}

const PERIOD_FUNCTIONS = { hour: 'toStartOfHour', day: 'toStartOfDay', week: 'toStartOfWeek', month: 'toStartOfMonth' }

function modelTrend<C extends Columns>(
    target: ModelDefinition<string, C>,
    options: ModelTrendOptions<C>
): InsightInput {
    const { sum, avg, min, max, timestamp, interval = 'day', ...fields } = options
    const [aggregate, column] = (Object.entries({ sum, avg, min, max }).find(([, value]) => value !== undefined) ?? [
        'count',
        undefined,
    ]) as [string, string | undefined]
    const time =
        timestamp ?? Object.entries(target.columns).find(([, type]) => type === 'date' || type === 'datetime')?.[0]
    const issues = [
        ...columnIssues(target, [column, timestamp], 'query'),
        ...(time === undefined
            ? [
                  {
                      code: 'column_undeclared',
                      message: `The model ${target.key} declares no date or datetime column to trend over. Declare one, or pass timestamp.`,
                      path: 'query',
                  },
              ]
            : []),
    ]
    const value = `${aggregate}(${column === undefined ? '' : hogqlIdentifier(column)})`
    const period = `${PERIOD_FUNCTIONS[interval]}(${hogqlIdentifier(time ?? 'timestamp')})`
    const input = hogql({
        name: `${target.key}: ${aggregate}${column ? ` of ${column}` : ''} by ${interval}`,
        ...fields,
        query: `SELECT ${period} AS period, ${value} AS value FROM ${hogqlIdentifier(target.key)} GROUP BY period ORDER BY period`,
        display: 'ActionsLineGraph',
        chartSettings: { xAxis: { column: 'period' }, yAxis: [{ column: 'value' }] },
    })
    // The SQL reads the model's table by name, so the model is created first.
    return withDependencies(withIssues(input, issues), [target])
}

function eventTrend<Props extends PropSpecs>(
    target: EventDefinition<string, Props>,
    { where, math, ...options }: EventTrendOptions<Props>
): InsightInput {
    const filters = Object.entries(where ?? {})
        .filter(([, value]) => value !== undefined)
        .sort(([a], [b]) => (a < b ? -1 : 1))
    const conditions = filters.map(([name, value]) => `${name} = ${String(value)}`).join(', ')
    return trend({
        name: conditions ? `${target.key} (${conditions})` : target.key,
        ...options,
        series: [
            {
                event: target.key,
                ...(math !== undefined ? { math } : {}),
                ...(filters.length > 0
                    ? {
                          properties: filters.map(
                              ([key, value]) =>
                                  ({ key, type: 'event', value, operator: 'exact' }) as NonNullable<
                                      EventsSeries['properties']
                                  >[number]
                          ),
                      }
                    : {}),
            },
        ],
    })
}

// A trends insight. Each series is an `EventsNode` unless it names another kind. Given an event, it
// counts that event; given a model, it charts one aggregate of a column over time with SQL.
export function trend(options: TrendOptions): InsightInput
export function trend<Props extends PropSpecs>(
    event: EventDefinition<string, Props>,
    options?: EventTrendOptions<Props>
): InsightInput
export function trend<C extends Columns>(model: ModelDefinition<string, C>, options: ModelTrendOptions<C>): InsightInput
export function trend(
    first: TrendOptions | EventDefinition | ModelDefinition,
    options?: EventTrendOptions<PropSpecs> | ModelTrendOptions<Columns>
): InsightInput {
    if (isDefinition(first)) {
        return first.kind === 'model'
            ? modelTrend(first as ModelDefinition, (options ?? {}) as ModelTrendOptions<Columns>)
            : eventTrend(first as EventDefinition, (options ?? {}) as EventTrendOptions<PropSpecs>)
    }
    const { series, ...rest } = first as TrendOptions
    const { fields, node } = split(rest)
    return withFields(fields, vizNode('TrendsQuery', { ...node, series: seriesNodes(series) }))
}

// A funnel insight. The steps are the query's series, in order.
export function funnel({ steps, ...options }: FunnelOptions): InsightInput {
    const { fields, node } = split(options)
    return withFields(fields, vizNode('FunnelsQuery', { ...node, series: seriesNodes(steps) }))
}
