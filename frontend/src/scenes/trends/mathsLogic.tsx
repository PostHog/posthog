import React from 'react'
import { kea } from 'kea'
import { groupsModel } from '~/models/groupsModel'

import { mathsLogicType } from './mathsLogicType'
import { EVENT_MATH_TYPE, PROPERTY_MATH_TYPE } from 'lib/constants'

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
    return math || 'total'
}

export const mathsLogic = kea<mathsLogicType>({
    path: ['scenes', 'trends', 'mathsLogic'],
    connect: {
        values: [groupsModel, ['groupTypes', 'aggregationLabel']],
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
            (s) => [s.groupsMathDefinitions],
            (groupOptions) => ({
                total: {
                    name: 'Total count',
                    description: (
                        <>
                            Total event count. Total number of times the event was performed by any user.
                            <br />
                            <br />
                            <i>Example: If a user performs an event 3 times in the given period, it counts as 3.</i>
                        </>
                    ),
                    onProperty: false,
                    type: EVENT_MATH_TYPE,
                },
                dau: {
                    name: 'Unique users',
                    description: (
                        <>
                            Number of unique users who performed the event in the specified period.
                            <br />
                            <br />
                            <i>
                                Example: If a single user performs an event 3 times in a given day/week/month, it counts
                                only as 1.
                            </i>
                        </>
                    ),
                    onProperty: false,
                    type: EVENT_MATH_TYPE,
                },
                weekly_active: {
                    name: 'Weekly active',
                    description: (
                        <>
                            Users active in the past week (7 days).
                            <br />
                            This is a trailing count that aggregates distinct users in the past 7 days for each day in
                            the time series
                        </>
                    ),
                    onProperty: false,
                    type: EVENT_MATH_TYPE,
                },
                monthly_active: {
                    name: 'Monthly active',
                    description: (
                        <>
                            Users active in the past month (30 days).
                            <br />
                            This is a trailing count that aggregates distinct users in the past 30 days for each day in
                            the time series
                        </>
                    ),
                    onProperty: false,
                    type: EVENT_MATH_TYPE,
                },
                ...groupOptions,
                avg: {
                    name: 'Average',
                    description: (
                        <>
                            Average of a property value within an event or action.
                            <br />
                            <br />
                            For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20,
                            result in 14.
                        </>
                    ),
                    onProperty: true,
                    type: PROPERTY_MATH_TYPE,
                },
                sum: {
                    name: 'Sum',
                    description: (
                        <>
                            Sum of property values within an event or action.
                            <br />
                            <br />
                            For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20,
                            result in 42.
                        </>
                    ),
                    onProperty: true,
                    type: PROPERTY_MATH_TYPE,
                },
                min: {
                    name: 'Minimum',
                    description: (
                        <>
                            Event property minimum.
                            <br />
                            <br />
                            For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20,
                            result in 10.
                        </>
                    ),
                    onProperty: true,
                    type: PROPERTY_MATH_TYPE,
                },
                max: {
                    name: 'Maximum',
                    description: (
                        <>
                            Event property maximum.
                            <br />
                            <br />
                            For example 3 events captured with property <code>amount</code> equal to 10, 12 and 20,
                            result in 20.
                        </>
                    ),
                    onProperty: true,
                    type: PROPERTY_MATH_TYPE,
                },
                median: {
                    name: 'Median',
                    description: (
                        <>
                            Event property median (50th percentile).
                            <br />
                            <br />
                            For example 100 events captured with property <code>amount</code> equal to 101..200, result
                            in 150.
                        </>
                    ),
                    onProperty: true,
                    type: PROPERTY_MATH_TYPE,
                },
                p90: {
                    name: '90th percentile',
                    description: (
                        <>
                            Event property 90th percentile.
                            <br />
                            <br />
                            For example 100 events captured with property <code>amount</code> equal to 101..200, result
                            in 190.
                        </>
                    ),
                    onProperty: true,
                    type: 'property',
                },
                p95: {
                    name: '95th percentile',
                    description: (
                        <>
                            Event property 95th percentile.
                            <br />
                            <br />
                            For example 100 events captured with property <code>amount</code> equal to 101..200, result
                            in 195.
                        </>
                    ),
                    onProperty: true,
                    type: PROPERTY_MATH_TYPE,
                },
                p99: {
                    name: '99th percentile',
                    description: (
                        <>
                            Event property 90th percentile.
                            <br />
                            <br />
                            For example 100 events captured with property <code>amount</code> equal to 101..200, result
                            in 199.
                        </>
                    ),
                    onProperty: true,
                    type: PROPERTY_MATH_TYPE,
                },
            }),
        ],
        groupsMathDefinitions: [
            (s) => [s.groupTypes, s.aggregationLabel],
            (groupTypes, aggregationLabel) =>
                Object.fromEntries(
                    groupTypes.map((groupType) => [
                        apiValueToMathType('unique_group', groupType.group_type_index),
                        {
                            name: `Unique ${aggregationLabel(groupType.group_type_index).plural}`,
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
                            type: EVENT_MATH_TYPE,
                        },
                    ])
                ),
        ],
    },
})
