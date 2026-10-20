import { useValues } from 'kea'

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
    COUNT_PER_ACTOR_MATH_DEFINITIONS,
    MathDefinition,
    PROPERTY_MATH_DEFINITIONS,
    mathsLogic,
} from 'products/product_analytics/frontend/insights/trends/mathsLogic'

import { SUPPORTED_PROPERTY_MATH_FOR_HISTOGRAM_BREAKDOWN } from './mathUtils'
import { MathAvailability } from './types'
import type { MathSelectorProps } from './types'

/** One math type the user can pick. */
export interface MathChoice {
    value: string
    /** The full name, shown in the trigger once picked. */
    label: string
    /** The name inside a nested choice list, such as "organizations" under "Unique". */
    shortLabel?: string
    description?: React.ReactNode
    /** Why this math type can mislead for the current query, if it can. */
    warning?: string
    disabledReason?: string
    dataAttr: string
}

/** A family of math types that differ by one sub-choice, such as the actor or the statistic. */
export interface MathChoiceGroup {
    label: string
    description?: React.ReactNode
    dataAttr: string
    choices: MathChoice[]
}

export type MathSelectorEntry = MathChoice | MathChoiceGroup

export interface MathSelectorChoices {
    entries: MathSelectorEntry[]
    /** Set when the groups introduction should show below the list. */
    groupsIntroduction: { needsUpgrade: boolean } | null
}

export function isMathChoiceGroup(entry: MathSelectorEntry): entry is MathChoiceGroup {
    return 'choices' in entry
}

export function flattenMathChoices(entries: MathSelectorEntry[]): MathChoice[] {
    return entries.flatMap((entry) => (isMathChoiceGroup(entry) ? entry.choices : [entry]))
}

const WARNING_TEXT: Record<'total' | 'weekly' | 'monthly', (name: string) => string> = {
    total: (name) =>
        `In total value insights, it's usually not clear what date range "${name}" refers to. For full clarity, we recommend using "Unique users" here instead.`,
    weekly: () =>
        'Weekly active users is not meaningful when using week or month intervals because the sliding window calculation cannot be properly applied. This query mode has the same functionality as "Unique users" for this interval.',
    monthly: () =>
        'Monthly active users is not meaningful when using month intervals because the sliding window calculation cannot be properly applied. This query mode has the same functionality as "Unique users" for this interval.',
}

/**
 * The math types a series can use, as plain data. This mirrors the options `useMathSelectorOptions`
 * builds for `LemonSelect`, but lists each sub-choice instead of embedding a picker in the option.
 */
export function useMathSelectorChoices({
    index,
    mathAvailability,
    trendsDisplayCategory,
    allowedMathTypes,
    excludedMathTypes,
    query,
}: Pick<
    MathSelectorProps,
    'index' | 'mathAvailability' | 'trendsDisplayCategory' | 'allowedMathTypes' | 'excludedMathTypes' | 'query'
>): MathSelectorChoices {
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
        firstTimeForGroupMathDefinitions,
        firstMatchingEventForGroupMathDefinitions,
    } = useValues(mathsLogic)

    let definitions = staticMathDefinitions
    if (mathAvailability === MathAvailability.FunnelsOnly) {
        definitions = funnelMathDefinitions
    } else if (mathAvailability === MathAvailability.ActorsOnly) {
        definitions = staticActorsOnlyMathDefinitions
    } else if (mathAvailability === MathAvailability.CalendarHeatmapOnly) {
        definitions = calendarHeatmapMathDefinitions
    }
    const isGroupsEnabled = !needsUpgradeForGroups && !canStartUsingGroups
    const isAllowed = (key: string): boolean => !allowedMathTypes || allowedMathTypes.includes(key)

    const entries: MathSelectorEntry[] = Object.entries(definitions)
        .filter((entry): entry is [string, MathDefinition] => !!entry[1])
        .filter(([key]) => {
            if (excludedMathTypes?.has(key.split('::')[0])) {
                return false
            }
            if (isStickiness) {
                return !TRAILING_MATH_TYPES.has(key as MathType)
            }
            if (allowedMathTypes) {
                return allowedMathTypes.includes(key.split('::')[0])
            }
            return true
        })
        .map(([key, definition]) => {
            const warning = getMathTypeWarning(key as MathType, query || {}, trendsDisplayCategory === 'TotalValue')
            return {
                value: key,
                label: definition.name,
                description: definition.description,
                warning: warning ? WARNING_TEXT[warning](definition.name) : undefined,
                dataAttr: `math-${key}-${index}`,
            }
        })

    if (
        mathAvailability !== MathAvailability.ActorsOnly &&
        mathAvailability !== MathAvailability.FunnelsOnly &&
        mathAvailability !== MathAvailability.CalendarHeatmapOnly &&
        mathAvailability !== MathAvailability.BoxPlotOnly
    ) {
        if (!allowedMathTypes || Object.values(CountPerActorMathType).some(isAllowed)) {
            entries.splice(1, 0, {
                label: 'Count per user',
                description: 'Statistical analysis of event count per user.',
                dataAttr: `math-node-count-per-actor-${index}`,
                choices: Object.entries(COUNT_PER_ACTOR_MATH_DEFINITIONS)
                    .filter(([key]) => isAllowed(key))
                    .map(([key, definition]) => ({
                        value: key,
                        label: `Count per user ${definition.shortName}`,
                        shortLabel: definition.shortName,
                        description: definition.description,
                        dataAttr: `math-${key}-${index}`,
                    })),
            })
        }

        if (!allowedMathTypes || Object.values(PropertyMathType).some(isAllowed)) {
            entries.push({
                label: 'Property value',
                description: 'Statistical analysis of property value.',
                dataAttr: `math-node-property-value-${index}`,
                choices: Object.entries(PROPERTY_MATH_DEFINITIONS)
                    .filter(([key]) => isAllowed(key))
                    .map(([key, definition]) => ({
                        value: key,
                        label: `Property value ${definition.shortName}`,
                        shortLabel: definition.shortName,
                        description: definition.description,
                        disabledReason:
                            isHistogramBreakdown &&
                            !SUPPORTED_PROPERTY_MATH_FOR_HISTOGRAM_BREAKDOWN.has(key as PropertyMathType)
                                ? 'Not supported when breaking down by a numeric property'
                                : undefined,
                        dataAttr: `math-${key}-${index}`,
                    })),
            })
        }
    }

    if (isGroupsEnabled && !isCalendarHeatmap && mathAvailability !== MathAvailability.BoxPlotOnly) {
        const replaceWithActorGroup = (
            baseMathType: BaseMathType,
            groupLabel: string,
            groupDataAttr: string,
            groupDefinitions: Record<string, MathDefinition | undefined>,
            choiceLabel: (actorPlural: string) => string,
            groupChoiceValue: (key: string) => string = (key) => key
        ): void => {
            const entryIndex = entries.findIndex((entry) => !isMathChoiceGroup(entry) && entry.value === baseMathType)
            if (entryIndex === -1) {
                return
            }
            const base = entries[entryIndex] as MathChoice
            entries[entryIndex] = {
                label: groupLabel,
                description: base.description,
                dataAttr: groupDataAttr,
                choices: [
                    { ...base, shortLabel: 'users', dataAttr: `math-users-${index}` },
                    ...Object.entries(groupDefinitions)
                        .filter((entry): entry is [string, MathDefinition] => !!entry[1])
                        .map(([key, definition]) => {
                            const actorPlural = aggregationLabel(Number(key.split('::')[1])).plural
                            return {
                                value: groupChoiceValue(key),
                                label: choiceLabel(actorPlural),
                                shortLabel: actorPlural,
                                description: definition.description,
                                dataAttr: `math-${key}-${index}`,
                            }
                        }),
                ],
            }
        }

        replaceWithActorGroup(
            BaseMathType.UniqueUsers,
            'Unique',
            `math-node-unique-actors-${index}`,
            groupsMathDefinitions,
            (actors) => `Unique ${actors}`
        )
        replaceWithActorGroup(
            BaseMathType.MonthlyActiveUsers,
            'Monthly active',
            `math-node-monthly-active-actors-${index}`,
            groupsMathDefinitions,
            (actors) => `Monthly active ${actors}`,
            (key) => `monthly_active::${key.split('::')[1]}`
        )
        replaceWithActorGroup(
            BaseMathType.WeeklyActiveUsers,
            'Weekly active',
            `math-node-weekly-active-actors-${index}`,
            groupsMathDefinitions,
            (actors) => `Weekly active ${actors}`,
            (key) => `weekly_active::${key.split('::')[1]}`
        )
        for (const [baseMathType, groupDefinitions] of [
            [BaseMathType.FirstTimeForUser, firstTimeForGroupMathDefinitions],
            [BaseMathType.FirstMatchingEventForUser, firstMatchingEventForGroupMathDefinitions],
        ] as const) {
            const baseName = staticMathDefinitions[baseMathType]?.name ?? ''
            replaceWithActorGroup(
                baseMathType,
                `${baseName} for`,
                `math-node-first-occurrence-${baseMathType}-${index}`,
                groupDefinitions,
                (actors) => `${baseName} for ${actors}`
            )
        }
    }

    if (
        mathAvailability !== MathAvailability.FunnelsOnly &&
        mathAvailability !== MathAvailability.CalendarHeatmapOnly &&
        mathAvailability !== MathAvailability.BoxPlotOnly &&
        isAllowed(HogQLMathType.HogQL)
    ) {
        entries.push({
            value: HogQLMathType.HogQL,
            label: 'SQL expression',
            description: 'Aggregate events by custom SQL expression.',
            dataAttr: `math-node-hogql-expression-${index}`,
        })
    }

    return {
        entries,
        groupsIntroduction: isGroupsEnabled ? null : { needsUpgrade: needsUpgradeForGroups },
    }
}
