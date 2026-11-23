import type {
    DataCatalogDataCatalogMetricCreateInput,
    DataQualityDataQualityCheckCreateInput,
} from '../generated/api.js'
import { type Definition, defineKind, isDefinition, ref, type Ref, withDependencies, withIssues } from './definition.js'
import type { InsightDefinition } from './insight.js'
import { columnIssues, hogqlIdentifier, type HogQLQueryNode, type ModelDefinition } from './model.js'

export interface MetricBody extends Omit<
    DataCatalogDataCatalogMetricCreateInput,
    'overwrite' | 'source_insight_short_id'
> {
    source_insight_short_id?: Ref<'insight'> | string | null
}

type ColumnOf<M> = M extends ModelDefinition<string, infer C> ? keyof C & string : string

export type Aggregate = 'sum' | 'avg' | 'min' | 'max' | 'count'

export interface MetricInput<M extends ModelDefinition, Dimension extends string> extends Omit<
    MetricBody,
    'name' | 'definition' | 'source_insight_short_id'
> {
    definition?: MetricBody['definition'] | HogQLQueryNode
    // An insight definition reads as a ref to its short id.
    source_insight_short_id?: InsightDefinition | Ref<'insight'> | string | null
    // Shorthand for a definition over one model column: `SELECT <aggregate>(<column>) AS value FROM <model>`.
    from?: M
    aggregate?: Aggregate
    column?: ColumnOf<M>
    // The model columns a metric can be broken down by. PostHog has no field for them yet, so
    // they type `DimensionsOf` and are checked against the model, and are not sent.
    dimensions?: readonly (Dimension & ColumnOf<M>)[]
}

export interface MetricExtra<Dimension extends string> {
    readonly dimensions: readonly Dimension[]
}

export type MetricDefinition<Name extends string = string, Dimension extends string = string> = Definition<
    'metric',
    Name,
    MetricBody
> &
    MetricExtra<Dimension>

export type DimensionsOf<M> = M extends MetricExtra<infer Dimension> ? Dimension : never

export function metric<
    const Name extends string,
    M extends ModelDefinition = ModelDefinition,
    const Dimension extends string = never,
>(name: Name, input: MetricInput<M, Dimension>): MetricDefinition<Name, Dimension> {
    const {
        from,
        aggregate = 'sum',
        column,
        dimensions = [],
        definition,
        source_insight_short_id: insight,
        ...fields
    } = input
    const issues = from
        ? [...columnIssues(from, [column], 'definition'), ...columnIssues(from, dimensions, 'dimensions')]
        : []
    const built =
        definition ??
        (from
            ? {
                  kind: 'HogQLQuery',
                  query: `SELECT ${aggregate}(${column === undefined ? '' : hogqlIdentifier(column)}) AS value FROM ${hogqlIdentifier(from.key)}`,
              }
            : undefined)
    const body: MetricBody = {
        ...fields,
        name,
        ...(built !== undefined ? { definition: built as NonNullable<MetricBody['definition']> } : {}),
        ...(insight !== undefined
            ? {
                  source_insight_short_id: isDefinition(insight)
                      ? ref(insight as InsightDefinition, 'short_id')
                      : insight,
              }
            : {}),
    }
    // The shorthand reads the model's table by name, so the model is created first.
    const ordered = withDependencies(withIssues(body, issues), from ? [from] : [])
    return defineKind('metric', name, ordered, {}, { dimensions: dimensions as readonly Dimension[] })
}

export interface CheckBody extends Omit<DataQualityDataQualityCheckCreateInput, 'subject_uuid'> {
    subject_uuid: Ref<'model'> | string
}

export interface CheckInput<M extends ModelDefinition> extends Omit<
    CheckBody,
    'subject_type' | 'subject_uuid' | 'column_name'
> {
    // A model in this stack, which sets `subject_type` to `view`. For anything else pass
    // `subject_type` and `subject_uuid` with the entity's id.
    subject?: M
    subject_type?: CheckBody['subject_type']
    subject_uuid?: string | Ref<'model'>
    column_name?: ColumnOf<M>
}

export type CheckDefinition<Key extends string = string> = Definition<'check', Key, CheckBody>

export function check<const Key extends string, M extends ModelDefinition = ModelDefinition>(
    key: Key,
    input: CheckInput<M>
): CheckDefinition<Key> {
    const { subject, subject_type, subject_uuid, column_name, ...fields } = input
    const issues = subject ? columnIssues(subject, [column_name], 'column_name') : []
    const body = {
        ...fields,
        subject_type: subject ? ('view' as const) : subject_type,
        subject_uuid: subject ? ref(subject) : subject_uuid,
        ...(column_name !== undefined ? { column_name } : {}),
    } as CheckBody
    return defineKind('check', key, withIssues(body, issues))
}
