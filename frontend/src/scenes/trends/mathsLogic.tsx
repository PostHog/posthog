import React from 'react'
import { kea } from 'kea'
import { groupsModel } from '~/models/groupsModel'
import type { mathsLogicType } from './mathsLogicType'
import { EVENT_MATH_TYPE, PROPERTY_MATH_TYPE } from 'lib/constants'
import { BaseMathType, PropertyMathType } from '~/types'
import { Tooltip } from 'lib/components/Tooltip'
import { LemonSelectOption, LemonSelectOptions, Link } from '@posthog/lemon-ui'
import { groupsAccessLogic, GroupsAccessStatus } from 'lib/introductions/groupsAccessLogic'

export interface MathDefinition {
    name: string
    /** Lowercase name variant for definitions where the full names is too verbose for summaries. */
    shortName: string
    description: string | JSX.Element
    onProperty: boolean
    actor: boolean
    type: 'property' | 'event'
}

function Label({ tooltip, children = null }: { tooltip?: string; children: React.ReactNode }): JSX.Element {
    return (
        <Tooltip title={tooltip} placement="left">
            <div className="w-full">{children}</div>
        </Tooltip>
    )
}

const GROUP_INTRODUCTION_OPTION: LemonSelectOption<BaseMathType | PropertyMathType | string> = {
    value: BaseMathType.WeeklyActive,
    disabled: true,
    label: (
        <Label>
            Unique Groups –{' '}
            <Link
                to="https://posthog.com/docs/user-guides/group-analytics?utm_medium=in-product&utm_campaign=group-analytics-learn-more"
                target="_blank"
                data-attr="group-analytics-learn-more"
                style={{ fontWeight: 600 }}
            >
                Learn more
            </Link>
        </Label>
    ),
}

export const SELECT_FORMATTED_OPTIONS: LemonSelectOptions<BaseMathType | PropertyMathType | string> = [
    {
        title: 'Event Aggregation',
        options: [
            {
                value: BaseMathType.Total,
                label: (
                    <Label
                        tooltip={
                            'Total event count. Total number of times the event was performed by any user. Example: If a user performs an event 3 times in the given period, it counts as 3.'
                        }
                    >
                        Total count
                    </Label>
                ),
            },
            {
                value: BaseMathType.DailyActive,
                label: (
                    <Label
                        tooltip={
                            'Number of unique users who performed the event in the specified period. Example: If a single user performs an event 3 times in a given day/week/month, it counts only as 1.'
                        }
                    >
                        Unique users
                    </Label>
                ),
            },
            {
                value: BaseMathType.WeeklyActive,
                label: (
                    <Label
                        tooltip={
                            'Users active in the past week (7 days). This is a trailing count that aggregates distinct users in the past 7 days for each day in the timeseries'
                        }
                    >
                        Weekly active
                    </Label>
                ),
            },
            {
                value: BaseMathType.MonthlyActive,
                label: (
                    <Label
                        tooltip={
                            'Users active in the past week (30 days). This is a trailing count that aggregates distinct users in the past 7 days for each day in the timeseries'
                        }
                    >
                        Monthly active
                    </Label>
                ),
            },
            {
                value: BaseMathType.UniqueSessions,
                label: (
                    <Label
                        tooltip={
                            'Number of unique sessions where the event was performed in the specified period. Example: If a single user performs an event 3 times in two separate sessions, it counts as two sessions.'
                        }
                    >
                        Unique Sessions
                    </Label>
                ),
            },
        ],
    },
    {
        title: 'Property Aggregation',
        options: [
            {
                value: PropertyMathType.Average,
                label: (
                    <Label
                        tooltip={
                            'Average of a property value within an event or action. For example 3 events captured with property amount equal to 10, 12 and 20, result in 14.'
                        }
                    >
                        Average
                    </Label>
                ),
            },
            {
                value: PropertyMathType.Sum,
                label: (
                    <Label
                        tooltip={
                            'Sum of property values within an event or action. For example 3 events captured with property'
                        }
                    >
                        Sum
                    </Label>
                ),
            },
            {
                value: PropertyMathType.Minimum,
                label: (
                    <Label
                        tooltip={
                            'Event property minimum. For example 3 events captured with property amount equal to 10, 12 and 20, result in 10.'
                        }
                    >
                        Minimum
                    </Label>
                ),
            },
            {
                value: PropertyMathType.Maximum,
                label: (
                    <Label
                        tooltip={
                            'Event property maximum. For example 3 events captured with property amount equal to 10, 12 and 20, result in 20.'
                        }
                    >
                        Maximum
                    </Label>
                ),
            },
            {
                value: PropertyMathType.Median,
                label: (
                    <Label
                        tooltip={
                            'Event property median (50th percentile). For example 100 events captured with property amount equal to 101..200, result in 150.'
                        }
                    >
                        Median
                    </Label>
                ),
            },
            {
                value: PropertyMathType.P90,
                label: (
                    <Label
                        tooltip={
                            'Event property 90th percentile. For example 3 events captured with property amount equal to 101..200, result in 190.'
                        }
                    >
                        90th Percentile
                    </Label>
                ),
            },
            {
                value: PropertyMathType.P95,
                label: (
                    <Label
                        tooltip={
                            'Event property 95th percentile. For example 3 events captured with property amount equal to 101..200, result in 195.'
                        }
                    >
                        95th Percentile
                    </Label>
                ),
            },
            {
                value: PropertyMathType.P99,
                label: (
                    <Label
                        tooltip={
                            'Event property 99th percentile. For example 3 events captured with property amount equal to 101..200, result in 199.'
                        }
                    >
                        99th Percentile
                    </Label>
                ),
            },
        ],
    },
]

export const BASE_MATH_DEFINITIONS: Record<BaseMathType, MathDefinition> = {
    [BaseMathType.Total]: {
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
        onProperty: false,
        actor: false,
        type: EVENT_MATH_TYPE,
    },
    [BaseMathType.DailyActive]: {
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
        onProperty: false,
        actor: true,
        type: EVENT_MATH_TYPE,
    },
    [BaseMathType.WeeklyActive]: {
        name: 'Weekly active',
        shortName: 'WAUs',
        description: (
            <>
                Users active in the past week (7 days).
                <br />
                This is a trailing count that aggregates distinct users in the past 7 days for each day in the time
                series
            </>
        ),
        onProperty: false,
        actor: false,
        type: EVENT_MATH_TYPE,
    },
    [BaseMathType.MonthlyActive]: {
        name: 'Monthly active',
        shortName: 'MAUs',
        description: (
            <>
                Users active in the past month (30 days).
                <br />
                This is a trailing count that aggregates distinct users in the past 30 days for each day in the time
                series
            </>
        ),
        onProperty: false,
        actor: false,
        type: EVENT_MATH_TYPE,
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
        onProperty: false,
        actor: false,
        type: EVENT_MATH_TYPE,
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
        onProperty: true,
        actor: false,
        type: PROPERTY_MATH_TYPE,
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
        onProperty: true,
        actor: false,
        type: PROPERTY_MATH_TYPE,
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
        onProperty: true,
        actor: false,
        type: PROPERTY_MATH_TYPE,
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
        onProperty: true,
        actor: false,
        type: PROPERTY_MATH_TYPE,
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
        onProperty: true,
        actor: false,
        type: PROPERTY_MATH_TYPE,
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
        onProperty: true,
        actor: false,
        type: 'property',
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
        onProperty: true,
        actor: false,
        type: PROPERTY_MATH_TYPE,
    },
    [PropertyMathType.P99]: {
        name: '99th percentile',
        shortName: '99th percentile',
        description: (
            <>
                Event property 90th percentile.
                <br />
                <br />
                For example 100 events captured with property <code>amount</code> equal to 101..200, result in 199.
            </>
        ),
        onProperty: true,
        actor: false,
        type: PROPERTY_MATH_TYPE,
    },
}

export function mathTypeToApiValues(mathType: string): {
    math: string
    math_group_type_index?: number | null | undefined
} {
    if (mathType.startsWith('unique_group')) {
        const index = mathType.split('::')[1]
        return { math: 'unique_group', math_group_type_index: +index }
    }
    return { math: mathType }
}

export function apiValueToMathType(math: string | undefined, groupTypeIndex: number | null | undefined): string {
    if (math === 'unique_group') {
        return `unique_group::${groupTypeIndex}`
    }
    return math || BaseMathType.Total
}

export const mathsLogic = kea<mathsLogicType>({
    path: ['scenes', 'trends', 'mathsLogic'],
    connect: {
        values: [groupsModel, ['groupTypes', 'aggregationLabel'], groupsAccessLogic, ['groupsAccessStatus']],
    },
    selectors: {
        eventMathEntries: [
            (s) => [s.mathDefinitions],
            (mathDefinitions) => Object.entries(mathDefinitions).filter(([, item]) => item.type == EVENT_MATH_TYPE),
        ],
        propertyMathEntries: [
            (s) => [s.mathDefinitions],
            (mathDefinitions) => Object.entries(mathDefinitions).filter(([, item]) => item.type == PROPERTY_MATH_TYPE),
        ],
        mathDefinitions: [
            (s) => [s.groupsMathDefinitions, s.groupsAccessStatus],
            (groupOptions): Record<string, MathDefinition> => {
                const allMathOptions: Record<string, MathDefinition> = {
                    ...BASE_MATH_DEFINITIONS,
                    ...groupOptions,
                    ...PROPERTY_MATH_DEFINITIONS,
                }
                return allMathOptions
            },
        ],
        selectFormattedOptions: [
            (s) => [s.groupsAccessStatus, s.groupsMathFormattedSelectDefinitions],
            (
                groupsAccessStatus,
                groupsMathFormattedSelectDefinitions
            ): LemonSelectOptions<BaseMathType | PropertyMathType | string> => {
                const hasGroupAccess = [
                    GroupsAccessStatus.HasAccess,
                    GroupsAccessStatus.HasGroupTypes,
                    GroupsAccessStatus.NoAccess,
                ].includes(groupsAccessStatus)
                const mathOptions = SELECT_FORMATTED_OPTIONS

                if (hasGroupAccess) {
                    mathOptions[0].options.push(GROUP_INTRODUCTION_OPTION)
                } else {
                    mathOptions[0].options.push(...groupsMathFormattedSelectDefinitions)
                }

                return mathOptions
            },
        ],
        groupsMathDefinitions: [
            (s) => [s.groupTypes, s.aggregationLabel],
            (groupTypes, aggregationLabel) =>
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
                                        Example: If a single ${aggregationLabel(groupType.group_type_index).singular}
                                        performs an event 3 times in the given period, it counts only as 1.
                                    </i>
                                </>
                            ),
                            onProperty: false,
                            actor: true,
                            type: EVENT_MATH_TYPE,
                        } as MathDefinition,
                    ])
                ),
        ],
        groupsMathFormattedSelectDefinitions: [
            (s) => [s.groupTypes, s.aggregationLabel],
            (groupTypes, aggregationLabel) =>
                groupTypes.map((groupType) => ({
                    value: apiValueToMathType('unique_group', groupType.group_type_index),
                    label: (
                        <Label
                            tooltip={`Number of unique ${
                                aggregationLabel(groupType.group_type_index).plural
                            } who performed the event in the specified period. Example: If a single ${
                                aggregationLabel(groupType.group_type_index).singular
                            }
                        performs an event 3 times in the given period, it counts only as 1.`}
                        >
                            Unique {aggregationLabel(groupType.group_type_index).plural}
                        </Label>
                    ),
                })),
        ],
    },
})
