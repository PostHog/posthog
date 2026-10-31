import {
    FEATURE_FLAG_CALLED_EVENT,
    FLAG_EVALUATIONS_RETENTION_DAYS,
    FLAG_EVALUATIONS_TABLE,
} from 'scenes/feature-flags/flagEvaluationsTable'
import { getHogQLValue } from 'scenes/insights/filters/aggregationTarget'

import {
    BreakdownFilter,
    DataWarehouseNode,
    FunnelsDataWarehouseNode,
    InsightQueryNode,
    LifecycleDataWarehouseNode,
    NodeKind,
} from '~/queries/schema/schema-general'
import { isAnyDataWarehouseNode } from '~/queries/utils'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import {
    AnyPropertyFilter,
    BaseMathType,
    DataWarehousePropertyFilter,
    GroupMathType,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

export const FLAG_CALLS_SERIES_NAME: string = CORE_FILTER_DEFINITIONS_BY_GROUP.events[FEATURE_FLAG_CALLED_EVENT].label

/** Replaces the event's core description on insight pickers where picking the event builds a flag calls series. */
export const FLAG_CALLS_SERIES_DESCRIPTION = `Sent by PostHog SDKs each time a feature flag is evaluated.

Insights include calls from the last ${FLAG_EVALUATIONS_RETENTION_DAYS} days. Filter or break down by \`flag_key\` and \`response\`.`

/** A picker keeps only the fields its own warehouse series kind takes. */
export const FLAG_EVALUATIONS_SERIES_FIELDS: Required<
    Pick<DataWarehouseNode, 'id_field' | 'timestamp_field' | 'distinct_id_field'> &
        Pick<FunnelsDataWarehouseNode, 'aggregation_target_field'> &
        Pick<LifecycleDataWarehouseNode, 'created_at_field'>
> = {
    id_field: 'uuid',
    timestamp_field: 'timestamp',
    distinct_id_field: 'distinct_id',
    // person_id is the merge-corrected person. A flag calls step counts the same person as an events step.
    aggregation_target_field: 'person_id',
    // Lifecycle calls a person new in the period the person was created, as it does on events.
    // withFlagCallsAggregationTarget swaps in the group's creation time when the query counts groups.
    created_at_field: 'person.created_at',
}

/** Trends computes these maths from events for every series. On a flag calls series they would count events, not flag calls. */
export const FLAG_CALLS_UNSUPPORTED_MATH_TYPES: ReadonlySet<string> = new Set<string>([
    BaseMathType.WeeklyActiveUsers,
    BaseMathType.MonthlyActiveUsers,
    BaseMathType.FirstTimeForUser,
    BaseMathType.FirstMatchingEventForUser,
    GroupMathType.FirstTimeForGroup,
    GroupMathType.FirstMatchingEventForGroup,
])

type SeriesOrRetentionEntity = { kind?: string; type?: string; table_name?: string } | null | undefined

function seriesNodes(query: InsightQueryNode): SeriesOrRetentionEntity[] {
    return query.kind === NodeKind.RetentionQuery
        ? [query.retentionFilter?.targetEntity, query.retentionFilter?.returningEntity]
        : 'series' in query
          ? (query.series ?? [])
          : []
}

function readsFlagCallsTable(node: SeriesOrRetentionEntity): boolean {
    return node?.table_name === FLAG_EVALUATIONS_TABLE
}

export function readsFlagCalls(query: InsightQueryNode): boolean {
    return seriesNodes(query).some(readsFlagCallsTable)
}

export function dataWarehouseSeriesNodes(query: InsightQueryNode): SeriesOrRetentionEntity[] {
    return seriesNodes(query).filter((node) => isAnyDataWarehouseNode(node) || node?.type === 'data_warehouse')
}

/**
 * Whether each data warehouse series in the query reads flag calls. True when there is none.
 * Mirrors every_warehouse_series_reads_flag_calls in posthog/hogql_queries/utils/entities.py.
 */
export function everyWarehouseSeriesReadsFlagCalls(query: InsightQueryNode): boolean {
    return dataWarehouseSeriesNodes(query).every(readsFlagCallsTable)
}

/** Sets the actor columns of each flag calls series to the query's aggregation.
 * The actor is a group key, the funnel's SQL expression, or the person.
 * A lifecycle series also gets the creation time of that group or person. */
export function withFlagCallsAggregationTarget<Q extends InsightQueryNode>(query: Q): Q {
    const groupTypeIndex = 'aggregation_group_type_index' in query ? query.aggregation_group_type_index : null
    // The flag_evaluations row carries the event's properties.
    // An expression such as properties.$session_id reads the same value there as on events.
    const aggregateByHogQL = query.kind === NodeKind.FunnelsQuery ? query.funnelsFilter?.funnelAggregateByHogQL : null
    const target = getHogQLValue(groupTypeIndex, aggregateByHogQL)
    const createdAtField =
        groupTypeIndex != null ? `group_${groupTypeIndex}.created_at` : FLAG_EVALUATIONS_SERIES_FIELDS.created_at_field
    const retarget = <T>(node: T): T => {
        const fields = node as
            | { table_name?: string; aggregation_target_field?: string; created_at_field?: string }
            | null
            | undefined
        if (fields?.table_name !== FLAG_EVALUATIONS_TABLE) {
            return node
        }
        const retargetsActor = fields.aggregation_target_field != null && fields.aggregation_target_field !== target
        const retargetsCreatedAt = fields.created_at_field != null && fields.created_at_field !== createdAtField
        return retargetsActor || retargetsCreatedAt
            ? {
                  ...node,
                  ...(retargetsActor ? { aggregation_target_field: target } : {}),
                  ...(retargetsCreatedAt ? { created_at_field: createdAtField } : {}),
              }
            : node
    }

    if (query.kind === NodeKind.RetentionQuery) {
        const { targetEntity, returningEntity } = query.retentionFilter ?? {}
        const nextTarget = retarget(targetEntity)
        const nextReturning = retarget(returningEntity)
        return nextTarget === targetEntity && nextReturning === returningEntity
            ? query
            : {
                  ...query,
                  retentionFilter: {
                      ...query.retentionFilter,
                      targetEntity: nextTarget,
                      returningEntity: nextReturning,
                  },
              }
    }
    if ('series' in query && query.series) {
        const series = query.series.map(retarget)
        return series.some((node, index) => node !== query.series[index]) ? { ...query, series } : query
    }
    return query
}

const FLAG_CALLS_COLUMN_BY_EVENT_PROPERTY: Record<string, string> = {
    $feature_flag: 'flag_key',
    $feature_flag_response: 'response',
}

/** Rewrites an event series' flag filters onto the flag_evaluations columns and keeps its SQL filters. */
export function flagCallsFiltersFromEventFilters(properties: AnyPropertyFilter[] | undefined): AnyPropertyFilter[] {
    return (properties ?? []).flatMap((property): AnyPropertyFilter[] => {
        if (property.type === PropertyFilterType.HogQL) {
            return [property]
        }
        if (property.type !== PropertyFilterType.Event) {
            return []
        }
        const column = FLAG_CALLS_COLUMN_BY_EVENT_PROPERTY[property.key]
        if (!column) {
            return []
        }
        // `flag_key` stores a missing key as '' rather than NULL, so its set checks compare against ''.
        let { value, operator } = property
        if (column === 'flag_key' && (operator === PropertyOperator.IsSet || operator === PropertyOperator.IsNotSet)) {
            value = ['']
            operator = operator === PropertyOperator.IsSet ? PropertyOperator.NotIn : PropertyOperator.In
        }
        const filter: DataWarehousePropertyFilter = {
            key: column,
            value,
            operator,
            type: PropertyFilterType.DataWarehouse,
        }
        return [filter]
    })
}

/** Rewrites event breakdowns on the flag properties onto the flag_evaluations columns. Other breakdowns stay as they are. */
export function flagCallsBreakdownFromEventBreakdown(
    breakdownFilter: BreakdownFilter | undefined
): BreakdownFilter | undefined {
    if (!breakdownFilter) {
        return breakdownFilter
    }
    if (breakdownFilter.breakdowns?.length) {
        const breakdowns = breakdownFilter.breakdowns.map((breakdown) => {
            const column =
                (breakdown.type ?? 'event') === 'event'
                    ? FLAG_CALLS_COLUMN_BY_EVENT_PROPERTY[String(breakdown.property)]
                    : undefined
            return column ? { ...breakdown, type: 'data_warehouse' as const, property: column } : breakdown
        })
        return breakdowns.some((breakdown, index) => breakdown !== breakdownFilter.breakdowns?.[index])
            ? { ...breakdownFilter, breakdowns }
            : breakdownFilter
    }
    const column =
        (breakdownFilter.breakdown_type ?? 'event') === 'event' && typeof breakdownFilter.breakdown === 'string'
            ? FLAG_CALLS_COLUMN_BY_EVENT_PROPERTY[breakdownFilter.breakdown]
            : undefined
    return column ? { ...breakdownFilter, breakdown_type: 'data_warehouse', breakdown: column } : breakdownFilter
}
