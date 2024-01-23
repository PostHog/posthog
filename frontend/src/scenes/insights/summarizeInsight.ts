import { useValues } from 'kea'
import { RETENTION_FIRST_TIME } from 'lib/constants'
import { KEY_MAPPING } from 'lib/taxonomy'
import { alphabet, capitalizeFirstLetter } from 'lib/utils'
import { toLocalFilters } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import {
    isFunnelsFilter,
    isLifecycleFilter,
    isPathsFilter,
    isRetentionFilter,
    isStickinessFilter,
    isTrendsFilter,
} from 'scenes/insights/sharedUtils'
import {
    getDisplayNameFromEntityFilter,
    getDisplayNameFromEntityNode,
    humanizePathsEventTypes,
} from 'scenes/insights/utils'
import { retentionOptions } from 'scenes/retention/constants'
import { apiValueToMathType, MathCategory, MathDefinition, mathsLogic } from 'scenes/trends/mathsLogic'
import { mathsLogicType } from 'scenes/trends/mathsLogicType'

import { cohortsModel } from '~/models/cohortsModel'
import { cohortsModelType } from '~/models/cohortsModelType'
import { groupsModel } from '~/models/groupsModel'
import { groupsModelType } from '~/models/groupsModelType'
import { extractExpressionComment } from '~/queries/nodes/DataTable/utils'
import { BreakdownFilter, InsightQueryNode, Node } from '~/queries/schema'
import {
    isDataTableNode,
    isEventsQuery,
    isFunnelsQuery,
    isHogQLQuery,
    isInsightVizNode,
    isLifecycleQuery,
    isPathsQuery,
    isPersonsNode,
    isRetentionQuery,
    isStickinessQuery,
    isTimeToSeeDataSessionsNode,
    isTimeToSeeDataSessionsQuery,
    isTrendsQuery,
} from '~/queries/utils'
import { AnyPartialFilterType, EntityFilter, FilterType, FunnelVizType, StepOrderValue } from '~/types'

function summarizeBreakdown(filters: Partial<FilterType> | BreakdownFilter, context: SummaryContext): string | null {
    const { breakdown_type, breakdown, breakdown_group_type_index } = filters
    if (breakdown) {
        if (breakdown_type === 'cohort') {
            const cohortIds = breakdown as (number | string)[]
            return `cohorts: ${cohortIds
                .map(
                    (cohortId) =>
                        cohortId &&
                        (cohortId === 'all'
                            ? 'all users'
                            : cohortId in context.cohortsById
                            ? context.cohortsById[cohortId]?.name
                            : `ID ${cohortId}`)
                )
                .join(', ')}`
        } else {
            const noun =
                breakdown_type !== 'group'
                    ? breakdown_type
                    : context.aggregationLabel(breakdown_group_type_index, true).singular
            return `${noun}'s ${
                (breakdown as string) in KEY_MAPPING.event ? KEY_MAPPING.event[breakdown as string].label : breakdown
            }`
        }
    }
    return null
}

function summarizeInsightFilters(filters: AnyPartialFilterType, context: SummaryContext): string {
    const localFilters = toLocalFilters(filters)

    if (isRetentionFilter(filters)) {
        const areTargetAndReturningIdentical =
            filters.returning_entity?.id === filters.target_entity?.id &&
            filters.returning_entity?.type === filters.target_entity?.type
        return (
            `Retention of ${context.aggregationLabel(filters.aggregation_group_type_index, true).plural}` +
            ` based on doing ${getDisplayNameFromEntityFilter((filters.target_entity || {}) as EntityFilter)}` +
            ` ${retentionOptions[filters.retention_type || RETENTION_FIRST_TIME]} and returning with ` +
            (areTargetAndReturningIdentical
                ? 'the same event'
                : getDisplayNameFromEntityFilter((filters.returning_entity || {}) as EntityFilter))
        )
    } else if (isPathsFilter(filters)) {
        // Sync format with PathsSummary in InsightDetails
        let summary = `User paths based on ${humanizePathsEventTypes(filters.include_event_types).join(' and ')}`
        if (filters.start_point) {
            summary += ` starting at ${filters.start_point}`
        }
        if (filters.end_point) {
            summary += `${filters.start_point ? ' and' : ''} ending at ${filters.end_point}`
        }
        return summary
    } else if (isLifecycleFilter(filters)) {
        return `User lifecycle based on ${getDisplayNameFromEntityFilter(localFilters[0])}`
    } else if (isFunnelsFilter(filters)) {
        let summary
        const linkSymbol =
            filters.funnel_order_type === StepOrderValue.STRICT
                ? '⇉'
                : filters.funnel_order_type === StepOrderValue.UNORDERED
                ? '&'
                : '→'
        summary = `${localFilters.map((filter) => getDisplayNameFromEntityFilter(filter)).join(` ${linkSymbol} `)} ${
            context.aggregationLabel(filters.aggregation_group_type_index, true).singular
        } conversion`
        if (filters.funnel_viz_type === FunnelVizType.TimeToConvert) {
            summary += ' time'
        } else if (filters.funnel_viz_type === FunnelVizType.Trends) {
            summary += ' trend'
        } else {
            // Steps are the default viz type
            summary += ' rate'
        }
        if (filters.breakdown_type) {
            summary += ` by ${summarizeBreakdown(filters, context)}`
        }
        return summary
    } else if (isStickinessFilter(filters)) {
        return capitalizeFirstLetter(
            localFilters
                .map((localFilter) => {
                    const actor = context.aggregationLabel(
                        localFilter.math === 'unique_group' ? localFilter.math_group_type_index : null,
                        true
                    ).singular
                    return `${actor} stickiness based on ${getDisplayNameFromEntityFilter(localFilter)}`
                })
                .join(' & ')
        )
    } else if (isTrendsFilter(filters)) {
        let summary = localFilters
            .map((localFilter, localFilterIndex) => {
                const mathType = apiValueToMathType(localFilter.math, localFilter.math_group_type_index)
                const mathDefinition = context.mathDefinitions[mathType] as MathDefinition | undefined
                let series: string
                if (mathDefinition?.category === MathCategory.EventCountPerActor) {
                    series = `${getDisplayNameFromEntityFilter(localFilter)} count per user ${mathDefinition.shortName}`
                } else if (mathDefinition?.category === MathCategory.PropertyValue) {
                    series = `${getDisplayNameFromEntityFilter(localFilter)}'s ${
                        KEY_MAPPING.event[localFilter.math_property as string]?.label || localFilter.math_property
                    } ${
                        mathDefinition
                            ? mathDefinition.shortName
                            : localFilter.math === 'unique_group'
                            ? 'unique groups'
                            : mathType
                    }`
                } else if (mathDefinition?.category === MathCategory.HogQLExpression) {
                    series = localFilter.math_hogql ?? 'HogQL'
                } else {
                    series = `${getDisplayNameFromEntityFilter(localFilter)} ${
                        mathDefinition
                            ? mathDefinition.shortName
                            : localFilter.math === 'unique_group'
                            ? 'unique groups'
                            : mathType
                    }`
                }
                if (filters.formula) {
                    series = `${alphabet[localFilterIndex].toUpperCase()}. ${series}`
                }
                return series
            })
            .join(' & ')

        if (filters.breakdown_type) {
            summary += `${localFilters.length > 1 ? ',' : ''} by ${summarizeBreakdown(filters, context)}`
        }
        if (filters.formula) {
            summary = `${filters.formula} on ${summary}`
        }

        return summary
    }
    return ''
}

export function summarizeInsightQuery(query: InsightQueryNode, context: SummaryContext): string {
    if (isTrendsQuery(query)) {
        let summary = query.series
            .map((s, index) => {
                const mathType = apiValueToMathType(s.math, s.math_group_type_index)
                const mathDefinition = context.mathDefinitions[mathType] as MathDefinition | undefined
                let series: string
                if (mathDefinition?.category === MathCategory.EventCountPerActor) {
                    series = `${getDisplayNameFromEntityNode(s)} count per user ${mathDefinition.shortName}`
                } else if (mathDefinition?.category === MathCategory.PropertyValue) {
                    series = `${getDisplayNameFromEntityNode(s)}'s ${
                        KEY_MAPPING.event[s.math_property as string]?.label || s.math_property
                    } ${
                        mathDefinition
                            ? mathDefinition.shortName
                            : s.math === 'unique_group'
                            ? 'unique groups'
                            : mathType
                    }`
                } else {
                    series = `${getDisplayNameFromEntityNode(s)} ${
                        mathDefinition
                            ? mathDefinition.shortName
                            : s.math === 'unique_group'
                            ? 'unique groups'
                            : mathType
                    }`
                }
                if (query.trendsFilter?.formula) {
                    series = `${alphabet[index].toUpperCase()}. ${series}`
                }
                return series
            })
            .join(' & ')

        if (query.breakdownFilter?.breakdown_type) {
            summary += `${query.series.length > 1 ? ',' : ''} by ${summarizeBreakdown(query.breakdownFilter, context)}`
        }
        if (query.trendsFilter?.formula) {
            summary = `${query.trendsFilter.formula} on ${summary}`
        }

        return summary
    } else if (isFunnelsQuery(query)) {
        let summary
        const linkSymbol =
            query.funnelsFilter?.funnelOrderType === StepOrderValue.STRICT
                ? '⇉'
                : query.funnelsFilter?.funnelOrderType === StepOrderValue.UNORDERED
                ? '&'
                : '→'
        summary = `${query.series.map((s) => getDisplayNameFromEntityNode(s)).join(` ${linkSymbol} `)} ${
            context.aggregationLabel(query.aggregation_group_type_index, true).singular
        } conversion`
        if (query.funnelsFilter?.funnelVizType === FunnelVizType.TimeToConvert) {
            summary += ' time'
        } else if (query.funnelsFilter?.funnelVizType === FunnelVizType.Trends) {
            summary += ' trend'
        } else {
            // Steps are the default viz type
            summary += ' rate'
        }
        if (query.breakdownFilter?.breakdown_type) {
            summary += ` by ${summarizeBreakdown(query.breakdownFilter, context)}`
        }
        return summary
    } else if (isRetentionQuery(query)) {
        const areTargetAndReturningIdentical =
            query.retentionFilter?.returningEntity?.id === query.retentionFilter?.targetEntity?.id &&
            query.retentionFilter?.returningEntity?.type === query.retentionFilter?.targetEntity?.type
        return (
            `Retention of ${context.aggregationLabel(query.aggregation_group_type_index, true).plural}` +
            ` based on doing ${getDisplayNameFromEntityFilter(
                (query.retentionFilter?.targetEntity || {}) as EntityFilter
            )}` +
            ` ${retentionOptions[query.retentionFilter?.retentionType || RETENTION_FIRST_TIME]} and returning with ` +
            (areTargetAndReturningIdentical
                ? 'the same event'
                : getDisplayNameFromEntityFilter((query.retentionFilter?.returningEntity || {}) as EntityFilter))
        )
    } else if (isPathsQuery(query)) {
        // Sync format with PathsSummary in InsightDetails
        let summary = `User paths based on ${humanizePathsEventTypes(query.pathsFilter?.includeEventTypes).join(
            ' and '
        )}`
        if (query.pathsFilter?.startPoint) {
            summary += ` starting at ${query.pathsFilter?.startPoint}`
        }
        if (query.pathsFilter?.endPoint) {
            summary += `${query.pathsFilter?.startPoint ? ' and' : ''} ending at ${query.pathsFilter?.endPoint}`
        }
        return summary
    } else if (isStickinessQuery(query)) {
        return capitalizeFirstLetter(
            query.series
                .map((s) => {
                    const actor = context.aggregationLabel(s.math_group_type_index, true).singular
                    return `${actor} stickiness based on ${getDisplayNameFromEntityNode(s)}`
                })
                .join(' & ')
        )
    } else if (isLifecycleQuery(query)) {
        return `User lifecycle based on ${getDisplayNameFromEntityNode(query.series[0])}`
    } else {
        return ''
    }
}

function summarizeQuery(query: Node): string {
    if (isHogQLQuery(query)) {
        return 'SQL query'
    }

    if (isTimeToSeeDataSessionsNode(query)) {
        return `Time to see data in ${
            query.source.sessionId ? `session ${query.source.sessionId}` : 'the current session'
        }`
    }

    if (isDataTableNode(query)) {
        if (isHogQLQuery(query.source)) {
            return summarizeQuery(query.source)
        }

        let selected: string[] = []
        let source = ''

        if (isEventsQuery(query.source)) {
            selected = [...query.source.select]
            source = 'events'
        } else if (isPersonsNode(query.source)) {
            selected = []
            source = 'persons'
        } else if (isTimeToSeeDataSessionsQuery(query.source)) {
            selected = ['sessions']
            source = 'time to see data stats'
        }

        if (query.columns) {
            selected = query.columns.slice()
        }

        if (selected.length > 0) {
            return `${selected
                .map(extractExpressionComment)
                .filter((c) => !query.hiddenColumns?.includes(c))
                .join(', ')}${source ? ` from ${source}` : ''}`
        }
    }

    return `${query?.kind} query`
}

export interface SummaryContext {
    aggregationLabel: groupsModelType['values']['aggregationLabel']
    cohortsById: cohortsModelType['values']['cohortsById']
    mathDefinitions: mathsLogicType['values']['mathDefinitions']
}

export function summarizeInsight(
    query: Node | undefined | null,
    filters: Partial<FilterType> | undefined | null,
    context: SummaryContext
): string {
    return isInsightVizNode(query)
        ? summarizeInsightQuery(query.source, context)
        : !!query && !isInsightVizNode(query)
        ? summarizeQuery(query)
        : filters && Object.keys(filters).length > 0
        ? summarizeInsightFilters(filters, context)
        : ''
}

export function useSummarizeInsight(): (query: Node | undefined | null, filters?: Partial<FilterType>) => string {
    const { aggregationLabel } = useValues(groupsModel)
    const { cohortsById } = useValues(cohortsModel)
    const { mathDefinitions } = useValues(mathsLogic)

    return (query, filters) =>
        summarizeInsight(query, filters || {}, { aggregationLabel, cohortsById, mathDefinitions })
}
