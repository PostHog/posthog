import { useValues } from 'kea'

import { PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE } from 'lib/components/PropertyFilters/utils'
import { RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS } from 'lib/constants'
import { alphabet, capitalizeFirstLetter } from 'lib/utils'
import {
    getDisplayNameFromEntityFilter,
    getDisplayNameFromEntityNode,
    humanizePathsEventTypes,
} from 'scenes/insights/utils'
import { retentionOptions } from 'scenes/retention/constants'
import { MathCategory, MathDefinition, apiValueToMathType, mathsLogic } from 'scenes/trends/mathsLogic'
import { mathsLogicType } from 'scenes/trends/mathsLogicType'

import { cohortsModel } from '~/models/cohortsModel'
import { cohortsModelType } from '~/models/cohortsModelType'
import { groupsModel } from '~/models/groupsModel'
import { groupsModelType } from '~/models/groupsModelType'
import { extractExpressionComment } from '~/queries/nodes/DataTable/utils'
import {
    Breakdown,
    BreakdownFilter,
    InsightQueryNode,
    MultipleBreakdownType,
    Node,
} from '~/queries/schema/schema-general'
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
    isTrendsQuery,
} from '~/queries/utils'
import { getCoreFilterDefinition } from '~/taxonomy/helpers'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import { BreakdownKeyType, BreakdownType, EntityFilter, FilterType, FunnelVizType, StepOrderValue } from '~/types'

function summarizeSingularBreakdown(
    breakdown: BreakdownKeyType | undefined,
    breakdownType: BreakdownType | MultipleBreakdownType | null | undefined,
    groupTypeIndex: number | null | undefined,
    context: SummaryContext
): string | null {
    if (!breakdown) {
        return null
    }

    const noun = breakdownType !== 'group' ? breakdownType : context.aggregationLabel(groupTypeIndex, true).singular
    const propertyLabel =
        typeof breakdown === 'string' &&
        breakdownType &&
        breakdownType in PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE
            ? getCoreFilterDefinition(breakdown, PROPERTY_FILTER_TYPE_TO_TAXONOMIC_FILTER_GROUP_TYPE[breakdownType])
                  ?.label || extractExpressionComment(breakdown)
            : extractExpressionComment(breakdown as string)
    return `${noun}'s ${propertyLabel}`
}

function summarizeMultipleBreakdown(
    filters: Partial<FilterType> | BreakdownFilter,
    context: SummaryContext
): string | null {
    const { breakdowns } = filters

    if (breakdowns && breakdowns.length > 0) {
        return (breakdowns as Breakdown[])
            .map((breakdown) =>
                summarizeSingularBreakdown(breakdown.property, breakdown.type, breakdown.group_type_index, context)
            )
            .filter((label): label is string => !!label)
            .join(', ')
    }

    return null
}

function summarizeBreakdown(filters: Partial<FilterType> | BreakdownFilter, context: SummaryContext): string | null {
    const { breakdown, breakdown_type, breakdown_group_type_index } = filters

    if (breakdown && breakdown_type === 'cohort') {
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
    }

    return (
        summarizeMultipleBreakdown(filters, context) ||
        summarizeSingularBreakdown(breakdown, breakdown_type, breakdown_group_type_index, context)
    )
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
                        CORE_FILTER_DEFINITIONS_BY_GROUP.event_properties[s.math_property as string]?.label ||
                        s.math_property
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

        if (
            query.breakdownFilter?.breakdown_type ||
            (query.breakdownFilter?.breakdowns && query.breakdownFilter.breakdowns.length > 0)
        ) {
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
        summary = `${query.series
            .map((s) => {
                let eventName = getDisplayNameFromEntityNode(s)
                if (s.optionalInFunnel) {
                    eventName += ' (optional)'
                }
                return eventName
            })
            .join(` ${linkSymbol} `)} ${
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
            ` ${retentionOptions[query.retentionFilter?.retentionType || RETENTION_FIRST_OCCURRENCE_MATCHING_FILTERS]} and returning with ` +
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
        return `${capitalizeFirstLetter(
            context.aggregationLabel(query.aggregation_group_type_index, true).singular
        )} lifecycle based on ${getDisplayNameFromEntityNode(query.series[0])}`
    }
    return ''
}

function summarizeQuery(query: Node): string {
    if (isHogQLQuery(query)) {
        return 'SQL query'
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

export function summarizeInsight(query: Node | undefined | null, context: SummaryContext): string {
    return isInsightVizNode(query)
        ? summarizeInsightQuery(query.source, context)
        : !!query && !isInsightVizNode(query)
          ? summarizeQuery(query)
          : ''
}

export function useSummarizeInsight(): (query: Node | undefined | null) => string {
    const { aggregationLabel } = useValues(groupsModel)
    const { cohortsById } = useValues(cohortsModel)
    const { mathDefinitions } = useValues(mathsLogic)

    return (query) => summarizeInsight(query, { aggregationLabel, cohortsById, mathDefinitions })
}
