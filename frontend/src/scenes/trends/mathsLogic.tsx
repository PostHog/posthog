import { kea } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import type { mathsLogicType } from './mathsLogicType'
import { BaseMathType, CountPerActorMathType, MathTypeGroup, PropertyMathType } from '~/types'
import { groupsAccessLogic } from 'lib/introductions/groupsAccessLogic'

export enum MathCategory {
    EventCount,
    SessionCount,
    ActorCount,
    EventCountPerActor,
    PropertyValue,
}

interface MathDefinitionBase {
    description: string | JSX.Element
    category: MathCategory
}

export interface StaticMathDefinition extends MathDefinitionBase {
    name: string
    /** Lowercase name variant for definitions where the full names is too verbose (e.g. insight summaries). */
    shortName: string
    functionDynamic?: never
    groupDynamic?: never
}

export interface FunctionDynamicMathDefinition extends MathDefinitionBase {
    functionDynamic: true
    groupDynamic?: never
    defaultOption: string
    Label: (props: { functionSelector: JSX.Element }) => JSX.Element
}

export interface GroupDynamicMathDefinition extends MathDefinitionBase {
    functionDynamic?: never
    groupDynamic: true
    Label: (props: { groupTypeSelector: JSX.Element }) => JSX.Element
}

export interface FunctionAndGroupDynamicMathDefinition extends MathDefinitionBase {
    functionDynamic: true
    groupDynamic: true
    defaultOption: string
    Label: (props: { functionSelector: JSX.Element; groupTypeSelector: JSX.Element }) => JSX.Element
}

export type MathDefinition =
    | StaticMathDefinition
    | FunctionDynamicMathDefinition
    | GroupDynamicMathDefinition
    | FunctionAndGroupDynamicMathDefinition
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

export const MATH_TYPE_GROUP_DEFINITIONS: Partial<Record<MathTypeGroup, Record<string, StaticMathDefinition>>> = {
    [MathTypeGroup.CountPerUser]: {
        [CountPerActorMathType.Average]: {
            name: 'Average',
            shortName: 'average',
            description: <>Event count per user average.</>,
            category: MathCategory.EventCountPerActor,
        },
        [CountPerActorMathType.Minimum]: {
            name: 'Minimum',
            shortName: 'minimum',
            description: <>Event count per user minimum.</>,
            category: MathCategory.EventCountPerActor,
        },
        [CountPerActorMathType.Maximum]: {
            name: 'Maximum',
            shortName: 'maximum',
            description: <>Event count per user maximum.</>,
            category: MathCategory.EventCountPerActor,
        },
        [CountPerActorMathType.Median]: {
            name: 'Median',
            shortName: 'median',
            description: <>Event count per user 50th percentile.</>,
            category: MathCategory.EventCountPerActor,
        },
        [CountPerActorMathType.P90]: {
            name: '90th percentile',
            shortName: '90th percentile',
            description: <>Event count per user 90th percentile.</>,
            category: MathCategory.EventCountPerActor,
        },
        [CountPerActorMathType.P95]: {
            name: '95th percentile',
            shortName: '95th percentile',
            description: <>Event count per user 95th percentile.</>,
            category: MathCategory.EventCountPerActor,
        },
        [CountPerActorMathType.P99]: {
            name: '99th percentile',
            shortName: '99th percentile',
            description: <>Event count per user 99th percentile.</>,
            category: MathCategory.EventCountPerActor,
        },
    },
    [MathTypeGroup.CountPerGroup]: {
        [CountPerActorMathType.Average]: {
            name: 'Average',
            shortName: 'average',
            description: <>Event count per group average.</>,
            category: MathCategory.EventCountPerActor,
        },
        [CountPerActorMathType.Minimum]: {
            name: 'Minimum',
            shortName: 'minimum',
            description: <>Event count per group minimum.</>,
            category: MathCategory.EventCountPerActor,
        },
        [CountPerActorMathType.Maximum]: {
            name: 'Maximum',
            shortName: 'maximum',
            description: <>Event count per group maximum.</>,
            category: MathCategory.EventCountPerActor,
        },
        [CountPerActorMathType.Median]: {
            name: 'Median',
            shortName: 'median',
            description: <>Event count per group 50th percentile.</>,
            category: MathCategory.EventCountPerActor,
        },
        [CountPerActorMathType.P90]: {
            name: '90th percentile',
            shortName: '90th percentile',
            description: <>Event count per group 90th percentile.</>,
            category: MathCategory.EventCountPerActor,
        },
        [CountPerActorMathType.P95]: {
            name: '95th percentile',
            shortName: '95th percentile',
            description: <>Event count per group 95th percentile.</>,
            category: MathCategory.EventCountPerActor,
        },
        [CountPerActorMathType.P99]: {
            name: '99th percentile',
            shortName: '99th percentile',
            description: <>Event count per group 99th percentile.</>,
            category: MathCategory.EventCountPerActor,
        },
    },
    [MathTypeGroup.PropertyValue]: {
        [PropertyMathType.Average]: {
            name: 'Average',
            shortName: 'average',
            description: (
                <>
                    Average of a property value within an event or action.
                    <br />
                    <br />
                    For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in
                    14.
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
                    For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in
                    42.
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
                    For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in
                    10.
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
                    For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20, result in
                    20.
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
    },
}

export const SELECTABLE_MATH_DEFINITIONS: Record<BaseMathType | MathTypeGroup, MathDefinition> = {
    [BaseMathType.TotalCount]: BASE_MATH_DEFINITIONS[BaseMathType.TotalCount],
    [MathTypeGroup.CountPerUser]: {
        description: 'Statistical analysis of event count per user.',
        functionDynamic: true,
        category: MathCategory.EventCountPerActor,
        defaultOption: CountPerActorMathType.Average,
        Label({ functionSelector }): JSX.Element {
            return (
                <div className="flex items-center gap-2">
                    <div>Count per user</div>
                    <div className="-mr-1">{functionSelector}</div>
                </div>
            )
        },
    } as FunctionDynamicMathDefinition,
    [MathTypeGroup.CountPerGroup]: {
        description: 'Statistical analysis of event count per user.',
        functionDynamic: true,
        groupDynamic: true,
        category: MathCategory.EventCountPerActor,
        defaultOption: CountPerActorMathType.Average,
        Label({ functionSelector, groupTypeSelector }): JSX.Element {
            return (
                <div className="flex items-center gap-2">
                    <div>Count per</div>
                    {groupTypeSelector}
                    <div>group</div>
                    <div className="-mr-1">{functionSelector}</div>
                </div>
            )
        },
    } as FunctionAndGroupDynamicMathDefinition,
    [BaseMathType.UniqueUsers]: BASE_MATH_DEFINITIONS[BaseMathType.UniqueUsers],
    [BaseMathType.UniqueSessions]: BASE_MATH_DEFINITIONS[BaseMathType.UniqueSessions],
    [BaseMathType.WeeklyActiveUsers]: BASE_MATH_DEFINITIONS[BaseMathType.WeeklyActiveUsers],
    [BaseMathType.MonthlyActiveUsers]: BASE_MATH_DEFINITIONS[BaseMathType.MonthlyActiveUsers],
    [MathTypeGroup.UniqueGroups]: {
        description: 'Number of groups where the event was performed in the specified period.',
        groupDynamic: true,
        category: MathCategory.ActorCount,
        defaultOption: CountPerActorMathType.Average,
        Label({ groupTypeSelector }): JSX.Element {
            return (
                <div className="flex items-center gap-2">
                    <div>Unique</div>
                    {groupTypeSelector}
                    <div>groups</div>
                </div>
            )
        },
    } as GroupDynamicMathDefinition,
    [MathTypeGroup.PropertyValue]: {
        description: 'Statistical analysis of property value.',
        functionDynamic: true,
        category: MathCategory.EventCountPerActor,
        defaultOption: PropertyMathType.Average,
        Label({ functionSelector }): JSX.Element {
            return (
                <div className="flex items-center gap-2">
                    <div>Property value</div>
                    <div className="-mr-1">{functionSelector}</div>
                </div>
            )
        },
    } as FunctionDynamicMathDefinition,
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
    if (math === MathTypeGroup.UniqueGroups) {
        assembledMath += `::${groupTypeIndex}`
    }
    return assembledMath
}

export const mathsLogic = kea<mathsLogicType>({
    path: ['scenes', 'trends', 'mathsLogic'],
    connect: {
        values: [
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
            groupsAccessLogic,
            ['needsUpgradeForGroups', 'canStartUsingGroups'],
        ],
    },
    selectors: {
        mathDefinitions: [
            (s) => [s.groupBasedMathDefinitions],
            (groupBasedMathDefinitions): Record<string, MathDefinition> => {
                const allMathDefinitions: Record<string, MathDefinition> = {
                    ...BASE_MATH_DEFINITIONS,
                    ...groupBasedMathDefinitions,
                    ...MATH_TYPE_GROUP_DEFINITIONS[MathTypeGroup.CountPerUser],
                    ...MATH_TYPE_GROUP_DEFINITIONS[MathTypeGroup.PropertyValue],
                }
                return allMathDefinitions
            },
        ],
        // Definitions based on group types present in the project
        groupBasedMathDefinitions: [
            (s) => [s.groupTypes, s.aggregationLabel],
            (groupTypes, aggregationLabel): Record<string, StaticMathDefinition> =>
                Object.fromEntries(
                    groupTypes.map((groupType) => [
                        apiValueToMathType('unique_group', groupType.group_type_index),
                        {
                            name: `Unique ${aggregationLabel(groupType.group_type_index).plural}`,
                            shortName: `unique ${aggregationLabel(groupType.group_type_index).plural}`,
                            description: (
                                <>
                                    Number of unique {aggregationLabel(groupType.group_type_index).plural} who performed
                                    the event in the specified period.
                                    <br />
                                    <br />
                                    <i>
                                        Example: If 7 users in a single $
                                        {aggregationLabel(groupType.group_type_index).singular}
                                        perform an event 9 times in the given period, it counts only as 1.
                                    </i>
                                </>
                            ),
                            category: MathCategory.ActorCount,
                        },
                    ])
                ),
        ],
    },
})
