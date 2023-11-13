import { kea, path, connect, selectors } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import type { mathsLogicType } from './mathsLogicType'
import { BaseMathType, CountPerActorMathType, HogQLMathType, PropertyMathType } from '~/types'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'

export enum MathCategory {
    EventCount,
    SessionCount,
    ActorCount,
    EventCountPerActor,
    PropertyValue,
    HogQLExpression,
}

export interface MathDefinition {
    name: string
    /** Lowercase name variant for definitions where the full names is too verbose (e.g. insight summaries). */
    shortName: string
    description: string | JSX.Element
    category: MathCategory
}

export const BASE_MATH_DEFINITIONS: Record<BaseMathType, MathDefinition> = {
    [BaseMathType.TotalCount]: {
        name: 'Total count',
        shortName: 'count',
        description: (
            <>
                Total event count. Total number of times the event was performed by any user.
                <br />
                <br />
                <i>Example: If a user performs an event 3 times in the given period, it counts as 3.</i>
            </>
        ),
        category: MathCategory.EventCount,
    },
    [BaseMathType.UniqueUsers]: {
        name: 'Unique users',
        shortName: 'unique users',
        description: (
            <>
                Number of unique users who performed the event in the specified period.
                <br />
                <br />
                <i>
                    Example: If a single user performs an event 3 times in a given day/week/month, it counts only as 1.
                </i>
            </>
        ),
        category: MathCategory.ActorCount,
    },
    [BaseMathType.WeeklyActiveUsers]: {
        name: 'Weekly active users',
        shortName: 'WAUs',
        description: (
            <>
                Users active in the past week (7 days).
                <br />
                This is a trailing count that aggregates distinct users in the past 7 days for each day in the time
                series
            </>
        ),
        category: MathCategory.ActorCount,
    },
    [BaseMathType.MonthlyActiveUsers]: {
        name: 'Monthly active users',
        shortName: 'MAUs',
        description: (
            <>
                Users active in the past month (30 days).
                <br />
                This is a trailing count that aggregates distinct users in the past 30 days for each day in the time
                series
            </>
        ),
        category: MathCategory.ActorCount,
    },
    [BaseMathType.UniqueSessions]: {
        name: 'Unique sessions',
        shortName: 'unique sessions',
        description: (
            <>
                Number of unique sessions where the event was performed in the specified period.
                <br />
                <br />
                <i>
                    Example: If a single user performs an event 3 times in two separate sessions, it counts as two
                    sessions.
                </i>
            </>
        ),
        category: MathCategory.SessionCount,
    },
}

export const PROPERTY_MATH_DEFINITIONS: Record<PropertyMathType, MathDefinition> = {
    [PropertyMathType.Average]: {
        name: 'Average',
        shortName: 'average',
        description: (
            <>
                Average of a property value within an event or action.
                <br />
                <br />
                For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in 14.
            </>
        ),
        category: MathCategory.PropertyValue,
    },
    [PropertyMathType.Sum]: {
        name: 'Sum',
        shortName: 'sum',
        description: (
            <>
                Sum of property values within an event or action.
                <br />
                <br />
                For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in 42.
            </>
        ),
        category: MathCategory.PropertyValue,
    },
    [PropertyMathType.Minimum]: {
        name: 'Minimum',
        shortName: 'minimum',
        description: (
            <>
                Event property minimum.
                <br />
                <br />
                For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in 10.
            </>
        ),
        category: MathCategory.PropertyValue,
    },
    [PropertyMathType.Maximum]: {
        name: 'Maximum',
        shortName: 'maximum',
        description: (
            <>
                Event property maximum.
                <br />
                <br />
                For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in 20.
            </>
        ),
        category: MathCategory.PropertyValue,
    },
    [PropertyMathType.Median]: {
        name: 'Median',
        shortName: 'median',
        description: (
            <>
                Event property median (50th percentile).
                <br />
                <br />
                For example 100 events captured with property <code>amount</code> equal to 101..200, result in 150.
            </>
        ),
        category: MathCategory.PropertyValue,
    },
    [PropertyMathType.P90]: {
        name: '90th percentile',
        shortName: '90th percentile',
        description: (
            <>
                Event property 90th percentile.
                <br />
                <br />
                For example 100 events captured with property <code>amount</code> equal to 101..200, result in 190.
            </>
        ),
        category: MathCategory.PropertyValue,
    },
    [PropertyMathType.P95]: {
        name: '95th percentile',
        shortName: '95th percentile',
        description: (
            <>
                Event property 95th percentile.
                <br />
                <br />
                For example 100 events captured with property <code>amount</code> equal to 101..200, result in 195.
            </>
        ),
        category: MathCategory.PropertyValue,
    },
    [PropertyMathType.P99]: {
        name: '99th percentile',
        shortName: '99th percentile',
        description: (
            <>
                Event property 99th percentile.
                <br />
                <br />
                For example 100 events captured with property <code>amount</code> equal to 101..200, result in 199.
            </>
        ),
        category: MathCategory.PropertyValue,
    },
}
export const HOGQL_MATH_DEFINITIONS: Record<HogQLMathType, MathDefinition> = {
    [HogQLMathType.HogQL]: {
        name: 'HogQL expression',
        shortName: 'HogQL expression',
        description: <>Aggregate with a custom HogQL expression.</>,
        category: MathCategory.HogQLExpression,
    },
}

export const COUNT_PER_ACTOR_MATH_DEFINITIONS: Record<CountPerActorMathType, MathDefinition> = {
    [CountPerActorMathType.Average]: {
        name: 'Average',
        shortName: 'average',
        description: <>Event count per actor average.</>,
        category: MathCategory.EventCountPerActor,
    },
    [CountPerActorMathType.Minimum]: {
        name: 'Minimum',
        shortName: 'minimum',
        description: <>Event count per actor minimum.</>,
        category: MathCategory.EventCountPerActor,
    },
    [CountPerActorMathType.Maximum]: {
        name: 'Maximum',
        shortName: 'maximum',
        description: <>Event count per actor maximum.</>,
        category: MathCategory.EventCountPerActor,
    },
    [CountPerActorMathType.Median]: {
        name: 'Median',
        shortName: 'median',
        description: <>Event count per actor 50th percentile.</>,
        category: MathCategory.EventCountPerActor,
    },
    [CountPerActorMathType.P90]: {
        name: '90th percentile',
        shortName: '90th percentile',
        description: <>Event count per actor 90th percentile.</>,
        category: MathCategory.EventCountPerActor,
    },
    [CountPerActorMathType.P95]: {
        name: '95th percentile',
        shortName: '95th percentile',
        description: <>Event count per actor 95th percentile.</>,
        category: MathCategory.EventCountPerActor,
    },
    [CountPerActorMathType.P99]: {
        name: '99th percentile',
        shortName: '99th percentile',
        description: <>Event count per actor 99th percentile.</>,
        category: MathCategory.EventCountPerActor,
    },
}

/** Deserialize a math selector value.
 *
 * Example: 'avg::1' is parsed into { math: 'avg', math_group_type_index: 1 } */
export function mathTypeToApiValues(mathType: string): {
    math: string
    math_group_type_index?: number
} {
    const [math, mathGroupTypeIndexRaw] = mathType.split('::')
    const mathGroupTypeIndex = mathGroupTypeIndexRaw !== undefined ? parseInt(mathGroupTypeIndexRaw) : NaN
    return !isNaN(mathGroupTypeIndex) ? { math, math_group_type_index: mathGroupTypeIndex } : { math }
}
/** Serialize a math selector value. Inverse of mathTypeToApiValues. */
export function apiValueToMathType(math: string | undefined, groupTypeIndex: number | null | undefined): string {
    let assembledMath = math || BaseMathType.TotalCount
    if (math === 'unique_group') {
        assembledMath += `::${groupTypeIndex}`
    }
    return assembledMath
}

export const mathsLogic = kea<mathsLogicType>([
    path(['scenes', 'trends', 'mathsLogic']),
    connect({
        values: [
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
            groupsAccessLogic,
            ['needsUpgradeForGroups', 'canStartUsingGroups'],
        ],
    }),
    selectors({
        mathDefinitions: [
            (s) => [s.groupsMathDefinitions],
            (groupsMathDefinitions): Record<string, MathDefinition> => {
                const allMathDefinitions: Record<string, MathDefinition> = {
                    ...BASE_MATH_DEFINITIONS,
                    ...groupsMathDefinitions,
                    ...PROPERTY_MATH_DEFINITIONS,
                    ...COUNT_PER_ACTOR_MATH_DEFINITIONS,
                    ...HOGQL_MATH_DEFINITIONS,
                }
                return allMathDefinitions
            },
        ],
        // Static means the options do not have nested selectors (like math function)
        staticMathDefinitions: [
            (s) => [s.groupsMathDefinitions, s.needsUpgradeForGroups],
            (groupsMathDefinitions, needsUpgradeForGroups): Record<string, MathDefinition> => {
                const staticMathDefinitions: Record<string, MathDefinition> = {
                    ...BASE_MATH_DEFINITIONS,
                    ...(!needsUpgradeForGroups ? groupsMathDefinitions : {}),
                }
                return staticMathDefinitions
            },
        ],
        staticActorsOnlyMathDefinitions: [
            (s) => [s.staticMathDefinitions],
            (staticMathDefinitions): Record<string, MathDefinition> => {
                return Object.fromEntries(
                    Object.entries(staticMathDefinitions).filter(
                        ([, mathDefinition]) => mathDefinition.category === MathCategory.ActorCount
                    )
                )
            },
        ],
        // Definitions based on group types present in the project
        groupsMathDefinitions: [
            (s) => [s.groupTypes, s.aggregationLabel],
            (groupTypes, aggregationLabel) =>
                Object.fromEntries(
                    Array.from(groupTypes.values())
                        .map((groupType) => [
                            apiValueToMathType('unique_group', groupType.group_type_index),
                            {
                                name: `Unique ${aggregationLabel(groupType.group_type_index).plural}`,
                                shortName: `unique ${aggregationLabel(groupType.group_type_index).plural}`,
                                description: (
                                    <>
                                        Number of unique {aggregationLabel(groupType.group_type_index).plural} who
                                        performed the event in the specified period.
                                        <br />
                                        <br />
                                        <i>
                                            Example: If 7 users in a single $
                                            {aggregationLabel(groupType.group_type_index).singular} perform an event 9
                                            times in the given period, it counts only as 1.
                                        </i>
                                    </>
                                ),
                                category: MathCategory.ActorCount,
                            } as MathDefinition,
                        ])
                        .filter(Boolean)
                ),
        ],
    }),
])
