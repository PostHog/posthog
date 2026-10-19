import { objectCleanWithEmpty } from 'lib/utils/objects'

import { cleanEntityProperties } from '~/queries/nodes/InsightQuery/utils/cleanProperties'
import { EntityNode, MathType } from '~/queries/schema/schema-general'
import { BaseMathType, CalendarHeatmapMathType, FunnelMathType, GroupMathType, HogQLMathType } from '~/types'

import { MathAvailability } from './ActionFilterRow/types'
import { SeriesNode, isGroupSeriesNode } from './seriesNode'

export const actorsOnlyMathTypes: readonly MathType[] = [
    BaseMathType.UniqueUsers,
    BaseMathType.WeeklyActiveUsers,
    BaseMathType.MonthlyActiveUsers,
    GroupMathType.UniqueGroup,
    HogQLMathType.HogQL,
]

export const funnelsMathTypes: readonly MathType[] = [
    FunnelMathType.FirstTimeForUser,
    FunnelMathType.FirstTimeForUserWithFilters,
]

export const calendarHeatmapMathTypes: readonly MathType[] = [
    CalendarHeatmapMathType.TotalCount,
    CalendarHeatmapMathType.UniqueUsers,
]

type SeriesMath = Pick<
    EntityNode,
    | 'math'
    | 'math_property'
    | 'math_property_type'
    | 'math_property_revenue_currency'
    | 'math_hogql'
    | 'math_group_type_index'
    | 'math_multiplier'
>

function allowedMath(seriesMath: SeriesMath, mathAvailability: MathAvailability): SeriesMath {
    const { math } = seriesMath
    switch (mathAvailability) {
        case MathAvailability.None:
            return {}
        case MathAvailability.FunnelsOnly:
            return math && funnelsMathTypes.includes(math) ? { math } : {}
        case MathAvailability.CalendarHeatmapOnly:
            return math && calendarHeatmapMathTypes.includes(math) ? { math } : {}
        case MathAvailability.ActorsOnly:
            // Stickiness counts actors, and the math selector has no option to show for any other math.
            if (!math || !actorsOnlyMathTypes.includes(math)) {
                return { math: BaseMathType.UniqueUsers }
            }
            return seriesMath
        default:
            return { ...seriesMath, math: math || BaseMathType.TotalCount }
    }
}

function cleanSeriesNode(node: SeriesNode, mathAvailability: MathAvailability, isFirstStep: boolean): SeriesNode {
    const {
        math,
        math_property,
        math_property_type,
        math_property_revenue_currency,
        math_hogql,
        math_group_type_index,
        math_multiplier,
        optionalInFunnel,
        name,
        custom_name,
        properties,
        ...rest
    } = node

    return objectCleanWithEmpty({
        ...rest,
        name: name || undefined,
        custom_name: custom_name || undefined,
        properties: cleanEntityProperties(properties),
        ...allowedMath(
            {
                math,
                math_property,
                math_property_type,
                math_property_revenue_currency,
                math_hogql,
                math_group_type_index,
                math_multiplier,
            },
            mathAvailability
        ),
        // The first step of a funnel cannot be optional.
        optionalInFunnel:
            mathAvailability === MathAvailability.FunnelsOnly && !isFirstStep && optionalInFunnel ? true : undefined,
        ...(isGroupSeriesNode(node)
            ? { nodes: node.nodes.map((nested) => cleanSeriesNode(nested, mathAvailability, false)) }
            : {}),
    }) as SeriesNode
}

/**
 * Prepares the series a picker emits for the query that stores them. Math the picker's
 * `MathAvailability` does not allow is dropped or replaced by that insight's default, unset and
 * empty fields go, and property filters are cleaned. Every other field is kept, including fields
 * the picker does not edit, such as `math_multiplier` or `funnelFromStep`.
 */
export function cleanSeriesNodes(series: SeriesNode[], mathAvailability: MathAvailability): SeriesNode[] {
    return series.map((node, index) => cleanSeriesNode(node, mathAvailability, index === 0))
}
