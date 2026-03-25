import { useValues } from 'kea'
import { useState } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonSelect, LemonSelectOption, LemonSelectOptions } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils'
import { GroupIntroductionFooter } from 'scenes/groups/GroupsIntroduction'
import {
    COUNT_PER_ACTOR_MATH_DEFINITIONS,
    MathDefinition,
    PROPERTY_MATH_DEFINITIONS,
    mathTypeToApiValues,
    mathsLogic,
} from 'scenes/trends/mathsLogic'

import { MathType } from '~/queries/schema/schema-general'
import {
    TRAILING_MATH_TYPES,
    getMathTypeWarning,
    isInsightVizNode,
    isStickinessQuery,
    isTrendsQuery,
} from '~/queries/utils'
import { BaseMathType, ChartDisplayType, CountPerActorMathType, HogQLMathType, PropertyMathType } from '~/types'

import {
    getDefaultPropertyMathType,
    isCountPerActorMath,
    SUPPORTED_PROPERTY_MATH_FOR_HISTOGRAM_BREAKDOWN,
} from './mathUtils'
import { MathAvailability } from './types'
import type { MathSelectorProps } from './types'

function getActiveActor(
    selectedMath: string,
    math: string | undefined,
    mathGroupTypeIndex: number | null | undefined,
    groupsMathDefinitions: Record<string, MathDefinition | undefined>
): string {
    if (mathGroupTypeIndex === undefined || mathGroupTypeIndex === null || selectedMath !== math) {
        return 'users'
    }
    const groupKey = `unique_group::${mathGroupTypeIndex}`
    const groupDef = groupsMathDefinitions[groupKey]
    return groupDef ? groupKey : 'users'
}

export function useMathSelectorOptions({
    math,
    index,
    mathAvailability,
    onMathSelect,
    trendsDisplayCategory,
    allowedMathTypes,
    query,
    mathGroupTypeIndex,
}: MathSelectorProps): LemonSelectOptions<string> {
    const isStickiness = query && isInsightVizNode(query) && isStickinessQuery(query.source)
    const isCalendarHeatmap =
        query &&
        isInsightVizNode(query) &&
        isTrendsQuery(query.source) &&
        query.source.trendsFilter?.display === ChartDisplayType.CalendarHeatmap
    const isHistogramBreakdown =
        query &&
        isInsightVizNode(query) &&
        isTrendsQuery(query.source) &&
        (query.source.breakdownFilter?.breakdown_histogram_bin_count != null ||
            query.source.breakdownFilter?.breakdowns?.some((b) => b.histogram_bin_count != null))

    const {
        needsUpgradeForGroups,
        canStartUsingGroups,
        staticMathDefinitions,
        funnelMathDefinitions,
        staticActorsOnlyMathDefinitions,
        calendarHeatmapMathDefinitions,

        aggregationLabel,
        groupsMathDefinitions,
    } = useValues(mathsLogic)

    const [propertyMathTypeShown, setPropertyMathTypeShown] = useState<PropertyMathType>(
        getDefaultPropertyMathType(math, allowedMathTypes)
    )

    const [countPerActorMathTypeShown, setCountPerActorMathTypeShown] = useState<CountPerActorMathType>(
        isCountPerActorMath(math) ? math : CountPerActorMathType.Average
    )

    const [uniqueActorsShown, setUniqueActorsShown] = useState<string>(
        getActiveActor('unique_group', math, mathGroupTypeIndex, groupsMathDefinitions)
    )
    const [weeklyActiveActorsShown, setWeeklyActiveActorsShown] = useState<string>(
        getActiveActor('weekly_active', math, mathGroupTypeIndex, groupsMathDefinitions)
    )
    const [monthlyActiveActorsShown, setMonthlyActiveActorsShown] = useState<string>(
        getActiveActor('monthly_active', math, mathGroupTypeIndex, groupsMathDefinitions)
    )

    let definitions = staticMathDefinitions
    if (mathAvailability === MathAvailability.FunnelsOnly) {
        definitions = funnelMathDefinitions
    } else if (mathAvailability === MathAvailability.ActorsOnly) {
        definitions = staticActorsOnlyMathDefinitions
    } else if (mathAvailability === MathAvailability.CalendarHeatmapOnly) {
        definitions = calendarHeatmapMathDefinitions
    }
    const isGroupsEnabled = !needsUpgradeForGroups && !canStartUsingGroups

    const options: LemonSelectOption<string>[] = Object.entries(definitions)
        .filter((entry): entry is [string, MathDefinition] => !!entry[1])
        .filter(([key]) => {
            const mathTypeKey = key as MathType
            if (isStickiness) {
                // Remove WAU and MAU from stickiness insights
                return !TRAILING_MATH_TYPES.has(mathTypeKey)
            }

            if (allowedMathTypes) {
                // The unique group keys are of the type 'unique_group::0', so need to strip the ::0
                // when comparing with the GroupMathType.UniqueGroup which has the value 'unique_group'
                const strippedKey = key.split('::')[0]
                return allowedMathTypes.includes(strippedKey)
            }

            return true
        })
        .map(([key, definition]) => {
            const mathTypeKey = key as MathType
            const warning = getMathTypeWarning(mathTypeKey, query || {}, trendsDisplayCategory === 'TotalValue')

            return {
                value: mathTypeKey,
                icon: warning !== null ? <IconWarning className="text-warning" /> : undefined,
                label: definition.name,
                'data-attr': `math-${key}-${index}`,
                tooltip:
                    warning === 'total' ? (
                        <>
                            <p>{definition.description}</p>
                            <i>
                                In total value insights, it's usually not clear what date range "{definition.name}"
                                refers to. For full clarity, we recommend using "Unique users" here instead.
                            </i>
                        </>
                    ) : warning === null ? (
                        definition.description
                    ) : (
                        <>
                            {warning === 'weekly' ? (
                                <p>
                                    Weekly active users is not meaningful when using week or month intervals because the
                                    sliding window calculation cannot be properly applied.
                                </p>
                            ) : (
                                <p>
                                    Monthly active users is not meaningful when using month intervals because the
                                    sliding window calculation cannot be properly applied.
                                </p>
                            )}
                            <span>This query mode has the same functionality as "Unique users" for this interval.</span>
                        </>
                    ),
            }
        })

    if (
        mathAvailability !== MathAvailability.ActorsOnly &&
        mathAvailability !== MathAvailability.FunnelsOnly &&
        mathAvailability !== MathAvailability.CalendarHeatmapOnly &&
        mathAvailability !== MathAvailability.BoxPlotOnly
    ) {
        {
            const shouldShowCountPerUser =
                !allowedMathTypes ||
                Object.values(CountPerActorMathType).some((type) => allowedMathTypes.includes(type))

            if (shouldShowCountPerUser) {
                options.splice(1, 0, {
                    value: countPerActorMathTypeShown,
                    label: `Count per user ${COUNT_PER_ACTOR_MATH_DEFINITIONS[countPerActorMathTypeShown].shortName}`,
                    labelInMenu: (
                        <div className="flex items-center gap-2">
                            <span>Count per user</span>
                            <LemonSelect
                                value={countPerActorMathTypeShown}
                                onSelect={(value) => {
                                    setCountPerActorMathTypeShown(value as CountPerActorMathType)
                                    onMathSelect(index, value)
                                }}
                                options={Object.entries(COUNT_PER_ACTOR_MATH_DEFINITIONS)
                                    .filter(([key]) => !allowedMathTypes || allowedMathTypes.includes(key))
                                    .map(([key, definition]) => ({
                                        value: key,
                                        label: definition.shortName,
                                        'data-attr': `math-${key}-${index}`,
                                    }))}
                                onClick={(e) => e.stopPropagation()}
                                size="small"
                                dropdownMatchSelectWidth={false}
                                optionTooltipPlacement="right"
                            />
                        </div>
                    ),
                    tooltip: 'Statistical analysis of event count per user.',
                    'data-attr': `math-node-count-per-actor-${index}`,
                })
            }
        }

        const shouldShowPropertyValue =
            !allowedMathTypes || Object.values(PropertyMathType).some((type) => allowedMathTypes.includes(type))

        if (shouldShowPropertyValue) {
            options.push({
                value: propertyMathTypeShown,
                label: `Property value ${PROPERTY_MATH_DEFINITIONS[propertyMathTypeShown].shortName}`,
                labelInMenu: (
                    <div className="flex items-center gap-2">
                        <span>Property value</span>
                        <LemonSelect
                            value={propertyMathTypeShown}
                            onSelect={(value) => {
                                setPropertyMathTypeShown(value as PropertyMathType)
                                onMathSelect(index, value)
                            }}
                            options={Object.entries(PROPERTY_MATH_DEFINITIONS)
                                .filter(([key]) => !allowedMathTypes || allowedMathTypes.includes(key))
                                .map(([key, definition]) => ({
                                    value: key,
                                    label: definition.shortName,
                                    tooltip: definition.description,
                                    'data-attr': `math-${key}-${index}`,
                                    disabledReason:
                                        isHistogramBreakdown &&
                                        // the backend raises an exception for queries that try to use unsupported math types
                                        // for histogram breakdowns, but it's a nicer UX if we just disallow it in the first place.
                                        !SUPPORTED_PROPERTY_MATH_FOR_HISTOGRAM_BREAKDOWN.has(key as PropertyMathType)
                                            ? 'Not supported when breaking down by a numeric property'
                                            : undefined,
                                }))}
                            onClick={(e) => e.stopPropagation()}
                            size="small"
                            dropdownMatchSelectWidth={false}
                            optionTooltipPlacement="right"
                        />
                    </div>
                ),
                tooltip: 'Statistical analysis of property value.',
                'data-attr': `math-node-property-value-${index}`,
            })
        }
    }

    if (isGroupsEnabled && !isCalendarHeatmap && mathAvailability !== MathAvailability.BoxPlotOnly) {
        const uniqueActorsOptions = [
            {
                value: 'users',
                label: 'users',
                'data-attr': `math-users-${index}`,
            },
            ...Object.entries(groupsMathDefinitions)
                .filter((entry): entry is [string, MathDefinition] => !!entry[1])
                .map(([key, definition]) => ({
                    value: key,
                    label: definition.shortName,
                    'data-attr': `math-${key}-${index}`,
                })),
        ]

        const uniqueUsersIndex = options.findIndex(
            (option) => 'value' in option && option.value === BaseMathType.UniqueUsers
        )
        if (uniqueUsersIndex !== -1) {
            const isDau = uniqueActorsShown === 'users'
            const value = isDau ? BaseMathType.UniqueUsers : uniqueActorsShown
            const label = isDau ? 'Unique users' : `Unique ${aggregationLabel(mathGroupTypeIndex).plural}`
            const tooltip = isDau
                ? options[uniqueUsersIndex].tooltip
                : groupsMathDefinitions[uniqueActorsShown]?.description
            options[uniqueUsersIndex] = {
                value,
                label,
                tooltip,
                labelInMenu: (
                    <div className="flex items-center gap-2">
                        <span>Unique</span>
                        <LemonSelect
                            value={uniqueActorsShown}
                            onClick={(e) => e.stopPropagation()}
                            size="small"
                            dropdownMatchSelectWidth={false}
                            optionTooltipPlacement="right"
                            onSelect={(value) => {
                                setUniqueActorsShown(value as string)
                                const mathType = value === 'users' ? BaseMathType.UniqueUsers : value
                                onMathSelect(index, mathType)
                            }}
                            options={uniqueActorsOptions}
                        />
                    </div>
                ),
                'data-attr': `math-node-unique-actors-${index}`,
            }
        }

        const getActiveActorOptionByPeriod = (
            activeActorShown: string,
            setActiveActorShown: (value: string) => void,
            mathType: BaseMathType,
            period: 'month' | 'week',
            days: '30' | '7',
            optionIndex: number
        ): LemonSelectOption<string> => {
            const baseOption = options[optionIndex] as LemonSelectOption<string>
            const isUsers = activeActorShown === 'users'
            const actor = isUsers ? 'users' : aggregationLabel(mathGroupTypeIndex).plural
            const capitalizedActor = capitalizeFirstLetter(actor)
            const label = `${capitalizeFirstLetter(period)}ly active ${actor}`
            const tooltip = isUsers ? (
                baseOption.tooltip
            ) : (
                <>
                    {baseOption.tooltip ? (
                        <>
                            {baseOption.tooltip}
                            <br />
                            <br />
                        </>
                    ) : null}
                    <b>
                        {capitalizedActor} active in the past {period} ({days} days).
                    </b>
                    <br />
                    <br />
                    This is a trailing count that aggregates distinct {actor} in the past {days} days for each day in
                    the time series.
                    <br />
                    <br />
                    If the group by interval is a {period} or longer, this is the same as "Unique {capitalizedActor} "
                    math.
                </>
            )

            return {
                ...baseOption,
                value: mathType,
                label,
                tooltip,
                'data-attr': `math-node-${period}ly-active-actors-${index}`,
                labelInMenu: (
                    <div className="flex items-center gap-2">
                        <span>{capitalizeFirstLetter(period)}ly active</span>
                        <LemonSelect
                            value={activeActorShown}
                            onClick={(e) => e.stopPropagation()}
                            size="small"
                            dropdownMatchSelectWidth={false}
                            optionTooltipPlacement="right"
                            onSelect={(value) => {
                                setActiveActorShown(value as string)
                                const groupIndex =
                                    value === 'users'
                                        ? undefined
                                        : mathTypeToApiValues(value as string).math_group_type_index
                                const resolvedMathType =
                                    groupIndex !== undefined ? `${period}ly_active::${groupIndex}` : mathType
                                onMathSelect(index, resolvedMathType)
                            }}
                            options={uniqueActorsOptions}
                        />
                    </div>
                ),
            }
        }

        const monthlyActiveUsersIndex = options.findIndex(
            (option) => 'value' in option && option.value === BaseMathType.MonthlyActiveUsers
        )
        if (monthlyActiveUsersIndex !== -1) {
            options[monthlyActiveUsersIndex] = getActiveActorOptionByPeriod(
                monthlyActiveActorsShown,
                setMonthlyActiveActorsShown,
                BaseMathType.MonthlyActiveUsers,
                'month',
                '30',
                monthlyActiveUsersIndex
            )
        }

        const weeklyActiveUsersIndex = options.findIndex(
            (option) => 'value' in option && option.value === BaseMathType.WeeklyActiveUsers
        )
        if (weeklyActiveUsersIndex !== -1) {
            options[weeklyActiveUsersIndex] = getActiveActorOptionByPeriod(
                weeklyActiveActorsShown,
                setWeeklyActiveActorsShown,
                BaseMathType.WeeklyActiveUsers,
                'week',
                '7',
                weeklyActiveUsersIndex
            )
        }
    }

    if (
        mathAvailability !== MathAvailability.FunnelsOnly &&
        mathAvailability !== MathAvailability.CalendarHeatmapOnly &&
        mathAvailability !== MathAvailability.BoxPlotOnly &&
        (!allowedMathTypes || allowedMathTypes.includes(HogQLMathType.HogQL))
    ) {
        options.push({
            value: HogQLMathType.HogQL,
            label: 'SQL expression',
            tooltip: 'Aggregate events by custom SQL expression.',
            'data-attr': `math-node-hogql-expression-${index}`,
        })
    }

    return [
        {
            options,
            footer: !isGroupsEnabled ? <GroupIntroductionFooter needsUpgrade={needsUpgradeForGroups} /> : undefined,
        },
    ]
}
