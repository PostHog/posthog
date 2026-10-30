import { ensureStringIsNotBlank } from 'lib/utils/strings'
import {
    SeriesNode,
    isActionsSeriesNode,
    isEventsSeriesNode,
    isGroupSeriesNode,
    isWarehouseSeriesNode,
} from 'scenes/insights/filters/ActionFilter/seriesNode'

import { InsightQueryNode } from '~/queries/schema/schema-general'
import { isInsightQueryWithSeries, isLifecycleQuery, isTrendsQuery } from '~/queries/utils'
import { BaseMathType, ChartDisplayType, IntervalType } from '~/types'

export type ResultSeriesMath = Pick<SeriesNode, 'math' | 'math_property' | 'math_hogql' | 'math_group_type_index'>

export interface ResultSeries {
    /** The index of the row's query series, or of its formula on a formula row. */
    order: number
    /**
     * The query series the row reports, carrying the name the row displays under. Null on a formula row, and on a
     * row whose series the query no longer holds, which happens while results for an edited query load.
     */
    node: SeriesNode | null
    math: ResultSeriesMath | null
}

export interface ResultSeriesRow {
    order?: number | null
}

/** A response's `action_names`: the name of each action the query's series reference, keyed by action id. */
export type ActionNames = Partial<Record<string, string>>

const WEEK_OR_LONGER_INTERVALS = new Set<IntervalType>(['week', 'month', 'quarter', 'year'])
const MONTH_OR_LONGER_INTERVALS = new Set<IntervalType>(['month', 'quarter', 'year'])

export function getResultOrder(result: ResultSeriesRow): number {
    return result.order ?? 0
}

/**
 * Whether the query returns formula rows in place of series rows. This mirrors the trends runner, which reads
 * `formulaNodes`, then `formulas`, then `formula`, and ignores an empty list or string. The calendar heatmap runner
 * ignores formulas and reports series 0, so its query keeps its formulas without returning formula rows.
 */
export function hasFormulaResults(querySource: InsightQueryNode | null | undefined): boolean {
    if (
        !isTrendsQuery(querySource) ||
        !querySource.trendsFilter ||
        querySource.trendsFilter.display === ChartDisplayType.CalendarHeatmap
    ) {
        return false
    }
    const { formulaNodes, formulas, formula } = querySource.trendsFilter
    return !!formulaNodes?.length || !!formulas?.length || !!formula
}

/** The query series index of a series row. Undefined on a formula row, because its `order` indexes the formulas. */
export function getResultSeriesIndex(
    querySource: InsightQueryNode | null | undefined,
    result: ResultSeriesRow
): number | undefined {
    return hasFormulaResults(querySource) ? undefined : getResultOrder(result)
}

/**
 * Pass the response's `action_names` wherever the series name is displayed, so that an action series saved without a
 * name displays the action's name.
 */
export function getResultSeries(
    querySource: InsightQueryNode | null | undefined,
    result: ResultSeriesRow,
    actionNames?: ActionNames
): ResultSeries {
    const order = getResultOrder(result)
    const node =
        querySource && !hasFormulaResults(querySource) && isInsightQueryWithSeries(querySource)
            ? (querySource.series[order] as SeriesNode | undefined)
            : undefined
    if (!node) {
        return { order, node: null, math: null }
    }
    return { order, node: withDisplayName(node, actionNames), math: getRunnerMath(querySource, node) }
}

/**
 * The key the runner labels a series with: its event, its table, or a group's member keys joined by commas. Null for
 * an all-events series, an action, and a group that holds an action saved without a name that `actionNames` does
 * not name.
 */
function getSeriesKey(node: SeriesNode, actionNames?: ActionNames): string | null {
    if (isEventsSeriesNode(node)) {
        return node.event ?? null
    }
    if (isWarehouseSeriesNode(node)) {
        return node.table_name
    }
    if (!isGroupSeriesNode(node)) {
        return null
    }
    const memberKeys = node.nodes.map((member) =>
        isEventsSeriesNode(member)
            ? (member.event ?? 'All events')
            : isActionsSeriesNode(member)
              ? (ensureStringIsNotBlank(member.name) ?? getActionName(member.id, actionNames))
              : getSeriesKey(member, actionNames)
    )
    return memberKeys.every((key) => key !== null) ? memberKeys.join(', ') : null
}

/**
 * The series' rename, by the rule the runner applies to `custom_name`: the custom name, or a `name` other than the
 * key the series queries. An action's key is its database name, which the query does not hold, so only its
 * `custom_name` counts.
 */
export function getResultSeriesCustomName(node: SeriesNode): string | null {
    const customName = ensureStringIsNotBlank(node.custom_name)
    if (customName) {
        return customName
    }
    const name = ensureStringIsNotBlank(node.name)
    return name && !isActionsSeriesNode(node) && name !== getSeriesKey(node) ? name : null
}

/**
 * A series saved without a `name` displays the raw key it queries, as the runner's label does. A nameless action
 * has no key in the query, so it takes the action's name from `actionNames`, as the runner takes it from the
 * database. So does a nameless action in a group.
 */
function withDisplayName(node: SeriesNode, actionNames: ActionNames | undefined): SeriesNode {
    if (ensureStringIsNotBlank(node.name)) {
        return node
    }
    const name = isEventsSeriesNode(node)
        ? node.event
        : isGroupSeriesNode(node)
          ? getSeriesKey(node, actionNames)
          : isActionsSeriesNode(node)
            ? getActionName(node.id, actionNames)
            : null
    return name ? { ...node, name } : node
}

function getActionName(id: number, actionNames: ActionNames | undefined): string | null {
    return ensureStringIsNotBlank(actionNames?.[id])
}

function getRunnerMath(querySource: InsightQueryNode | null | undefined, node: SeriesNode): ResultSeriesMath {
    if (isLifecycleQuery(querySource)) {
        return { math: BaseMathType.TotalCount }
    }
    if (!isTrendsQuery(querySource)) {
        // The stickiness runner applies the series math but does not report it, so its labels never show a math tag.
        return {}
    }
    return {
        math: getTrendsRunnerMath(node.math, querySource.interval ?? 'day'),
        math_property: node.math_property,
        math_hogql: node.math_hogql,
        math_group_type_index: node.math_group_type_index,
    }
}

/**
 * The trends runner counts weekly or monthly active users as daily active users when one interval bucket already
 * spans the trailing window, so the series math is the daily one for those intervals.
 */
function getTrendsRunnerMath(math: ResultSeriesMath['math'], interval: IntervalType): ResultSeriesMath['math'] {
    if (
        (math === BaseMathType.WeeklyActiveUsers && WEEK_OR_LONGER_INTERVALS.has(interval)) ||
        (math === BaseMathType.MonthlyActiveUsers && MONTH_OR_LONGER_INTERVALS.has(interval))
    ) {
        return BaseMathType.UniqueUsers
    }
    return math
}
