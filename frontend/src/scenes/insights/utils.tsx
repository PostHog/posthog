import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from 'lib/taxonomy'
import { ensureStringIsNotBlank, humanFriendlyNumber, objectsEqual } from 'lib/utils'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { ReactNode } from 'react'
import { urls } from 'scenes/urls'

import { FormatPropertyValueForDisplayFunction } from '~/models/propertyDefinitionsModel'
import { examples } from '~/queries/examples'
import { ActionsNode, BreakdownFilter, DataWarehouseNode, EventsNode, PathsFilter } from '~/queries/schema'
import { isDataWarehouseNode, isEventsNode } from '~/queries/utils'
import {
    ActionFilter,
    AnyPartialFilterType,
    BreakdownKeyType,
    ChartDisplayType,
    CohortType,
    EntityFilter,
    EntityTypes,
    EventType,
    InsightShortId,
    InsightType,
    PathType,
    TrendsFilterType,
} from '~/types'

import { insightLogic } from './insightLogic'

export const isAllEventsEntityFilter = (filter: EntityFilter | ActionFilter | null): boolean => {
    return (
        filter !== null &&
        filter.type === EntityTypes.EVENTS &&
        filter.id === null &&
        (!filter.name || filter.name === 'All events')
    )
}

export const getDisplayNameFromEntityFilter = (
    filter: EntityFilter | ActionFilter | null,
    isCustom = true
): string | null => {
    // Make sure names aren't blank strings
    const customName = ensureStringIsNotBlank(filter?.custom_name)
    let name = ensureStringIsNotBlank(filter?.name)
    if (name && name in CORE_FILTER_DEFINITIONS_BY_GROUP.events) {
        name = CORE_FILTER_DEFINITIONS_BY_GROUP.events[name].label
    }
    if (isAllEventsEntityFilter(filter)) {
        name = 'All events'
    }

    // Return custom name. If that doesn't exist then the name, then the id, then just null.
    return (isCustom ? customName : null) ?? name ?? (filter?.id ? `${filter?.id}` : null)
}

export const getDisplayNameFromEntityNode = (
    node: EventsNode | ActionsNode | DataWarehouseNode,
    isCustom = true
): string | null => {
    // Make sure names aren't blank strings
    const customName = ensureStringIsNotBlank(node?.custom_name)
    let name = ensureStringIsNotBlank(node?.name)
    if (name && name in CORE_FILTER_DEFINITIONS_BY_GROUP.events) {
        name = CORE_FILTER_DEFINITIONS_BY_GROUP.events[name].label
    }
    if (isEventsNode(node) && node.event === null) {
        name = 'All events'
    }

    const id = isDataWarehouseNode(node) ? node.table_name : isEventsNode(node) ? node.event : node.id

    // Return custom name. If that doesn't exist then the name, then the id, then just null.
    return (isCustom ? customName : null) ?? name ?? (id ? `${id}` : null)
}

export function extractObjectDiffKeys(
    oldObj: AnyPartialFilterType,
    newObj: AnyPartialFilterType,
    prefix: string = ''
): Record<string, any> {
    if (Object.keys(oldObj).length === 0) {
        return []
    }

    let changedKeys: Record<string, any> = {}
    for (const [key, value] of Object.entries(newObj)) {
        const valueOrArray = value || []
        const oldValue = (oldObj as Record<string, any>)[key] || []
        if (!objectsEqual(value, oldValue)) {
            if (key === 'events') {
                const events = valueOrArray as Record<string, any>[]
                if (events.length !== oldValue.length) {
                    changedKeys['changed_events_length'] = oldValue?.length
                } else {
                    events.forEach((event, idx) => {
                        changedKeys = {
                            ...changedKeys,
                            ...extractObjectDiffKeys(oldValue[idx], event, `event_${idx}_`),
                        }
                    })
                }
            } else if (key === 'actions') {
                const actions = valueOrArray as Record<string, any>[]
                if (actions.length !== oldValue.length) {
                    changedKeys['changed_actions_length'] = oldValue.length
                } else {
                    actions.forEach((action, idx) => {
                        changedKeys = {
                            ...changedKeys,
                            ...extractObjectDiffKeys(oldValue[idx], action, `action_${idx}_`),
                        }
                    })
                }
            } else {
                changedKeys[`changed_${prefix}${key}`] = oldValue
            }
        }
    }

    return changedKeys
}

export async function getInsightId(shortId: InsightShortId): Promise<number | undefined> {
    const insightId = insightLogic.findMounted({ dashboardItemId: shortId })?.values?.queryBasedInsight?.id

    return insightId
        ? insightId
        : (await api.get(`api/projects/${getCurrentTeamId()}/insights/?short_id=${encodeURIComponent(shortId)}`))
              .results[0]?.id
}

export function humanizePathsEventTypes(includeEventTypes: PathsFilter['includeEventTypes']): string[] {
    let humanEventTypes: string[] = []
    if (includeEventTypes) {
        if (includeEventTypes.includes(PathType.PageView)) {
            humanEventTypes.push('page views')
        }
        if (includeEventTypes.includes(PathType.Screen)) {
            humanEventTypes.push('screen views')
        }
        if (includeEventTypes.includes(PathType.CustomEvent)) {
            humanEventTypes.push('custom events')
        }
        if (
            (humanEventTypes.length === 0 && !includeEventTypes.includes(PathType.HogQL)) ||
            humanEventTypes.length === 3
        ) {
            humanEventTypes = ['all events']
        }
        if (includeEventTypes.includes(PathType.HogQL)) {
            humanEventTypes.push('HogQL expression')
        }
    }
    return humanEventTypes
}

export function formatAggregationValue(
    property: string | undefined,
    propertyValue: number | null,
    renderCount: (value: number) => ReactNode = (x) => <>{humanFriendlyNumber(x)}</>,
    formatPropertyValueForDisplay?: FormatPropertyValueForDisplayFunction
): ReactNode {
    if (propertyValue === null) {
        return '-'
    }

    let formattedValue: ReactNode
    if (property && formatPropertyValueForDisplay) {
        formattedValue = formatPropertyValueForDisplay(property, propertyValue)
        // yes, double equals not triple equals  ¯\_(ツ)_/¯ let JS compare strings and numbers however it wants
        if (formattedValue == propertyValue) {
            // formatPropertyValueForDisplay didn't change the value...
            formattedValue = renderCount(propertyValue)
        }
    } else {
        formattedValue = renderCount(propertyValue)
    }

    // Since `propertyValue` is a number. `formatPropertyValueForDisplay` will only return a string
    // To make typescript happy we handle the possible but impossible string array inside this function
    return Array.isArray(formattedValue) ? formattedValue[0] : formattedValue
}

// NB! Sync this with breakdown_values.py
export const BREAKDOWN_OTHER_STRING_LABEL = '$$_posthog_breakdown_other_$$'
export const BREAKDOWN_OTHER_NUMERIC_LABEL = 9007199254740991 // pow(2, 53) - 1
export const BREAKDOWN_OTHER_DISPLAY = 'Other (i.e. all remaining values)'
export const BREAKDOWN_NULL_STRING_LABEL = '$$_posthog_breakdown_null_$$'
export const BREAKDOWN_NULL_NUMERIC_LABEL = 9007199254740990 // pow(2, 53) - 2
export const BREAKDOWN_NULL_DISPLAY = 'None (i.e. no value)'

export function isOtherBreakdown(breakdown_value: string | number | null | undefined | ReactNode): boolean {
    return (
        breakdown_value === BREAKDOWN_OTHER_STRING_LABEL ||
        breakdown_value === BREAKDOWN_OTHER_NUMERIC_LABEL ||
        String(breakdown_value) === String(BREAKDOWN_OTHER_NUMERIC_LABEL)
    )
}

export function isNullBreakdown(breakdown_value: string | number | null | undefined): boolean {
    return (
        breakdown_value === BREAKDOWN_NULL_STRING_LABEL ||
        breakdown_value === BREAKDOWN_NULL_NUMERIC_LABEL ||
        String(breakdown_value) === String(BREAKDOWN_NULL_NUMERIC_LABEL)
    )
}

function isValidJsonArray(maybeJson: string): boolean {
    try {
        const json = JSON.parse(maybeJson)
        return Array.isArray(json)
    } catch {
        return false
    }
}

export function formatBreakdownLabel(
    breakdown_value: BreakdownKeyType | undefined,
    breakdownFilter: BreakdownFilter | null | undefined,
    cohorts: CohortType[] | undefined,
    formatPropertyValueForDisplay: FormatPropertyValueForDisplayFunction | undefined
): string {
    if (
        breakdownFilter?.breakdown_histogram_bin_count != null &&
        typeof breakdown_value === 'string' &&
        breakdown_value.length > 0 &&
        isValidJsonArray(breakdown_value)
    ) {
        // replace nan with null
        const bucketValues = breakdown_value.replace(/\bnan\b/g, 'null')
        const [bucketStart, bucketEnd] = JSON.parse(bucketValues)
        const formattedBucketStart = formatBreakdownLabel(
            bucketStart,
            breakdownFilter,
            cohorts,
            formatPropertyValueForDisplay
        )
        const formattedBucketEnd = formatBreakdownLabel(
            bucketEnd,
            breakdownFilter,
            cohorts,
            formatPropertyValueForDisplay
        )
        if (formattedBucketStart === formattedBucketEnd) {
            return formattedBucketStart
        }
        return `${formattedBucketStart} – ${formattedBucketEnd}`
    } else if (breakdownFilter?.breakdown_type === 'cohort') {
        // :TRICKY: Different endpoints represent the all users cohort breakdown differently
        if (breakdown_value === 0 || breakdown_value === 'all') {
            return 'All Users'
        }
        return cohorts?.filter((c) => c.id == breakdown_value)[0]?.name ?? (breakdown_value || '').toString()
    } else if (typeof breakdown_value == 'number') {
        return isOtherBreakdown(breakdown_value)
            ? BREAKDOWN_OTHER_DISPLAY
            : isNullBreakdown(breakdown_value)
            ? BREAKDOWN_NULL_DISPLAY
            : formatPropertyValueForDisplay
            ? formatPropertyValueForDisplay(breakdownFilter?.breakdown, breakdown_value)?.toString() ?? 'None'
            : String(breakdown_value)
    } else if (typeof breakdown_value == 'string') {
        return isOtherBreakdown(breakdown_value) || breakdown_value === 'nan'
            ? BREAKDOWN_OTHER_DISPLAY
            : isNullBreakdown(breakdown_value) || breakdown_value === ''
            ? BREAKDOWN_NULL_DISPLAY
            : breakdown_value
    } else if (Array.isArray(breakdown_value)) {
        return breakdown_value
            .map((v) => formatBreakdownLabel(v, breakdownFilter, cohorts, formatPropertyValueForDisplay))
            .join('::')
    }
    return ''
}

export function formatBreakdownType(breakdownFilter: BreakdownFilter): string {
    if (breakdownFilter.breakdown_type === 'cohort') {
        return 'Cohort'
    }
    return breakdownFilter?.breakdown?.toString() || 'Breakdown Value'
}

export function sortDates(dates: Array<string | null>): Array<string | null> {
    return dates.sort((a, b) => (dayjs(a).isAfter(dayjs(b)) ? 1 : -1))
}

export function sortDayJsDates(dates: Array<dayjs.Dayjs>): Array<dayjs.Dayjs> {
    return dates.sort((a, b) => (a.isAfter(b) ? 1 : -1))
}

// Gets content-length header from a fetch Response
export function getResponseBytes(apiResponse: Response): number {
    return parseInt(apiResponse.headers.get('Content-Length') ?? '0')
}

export const insightTypeURL = {
    TRENDS: urls.insightNew({ insight: InsightType.TRENDS }),
    STICKINESS: urls.insightNew({ insight: InsightType.STICKINESS }),
    LIFECYCLE: urls.insightNew({ insight: InsightType.LIFECYCLE }),
    FUNNELS: urls.insightNew({ insight: InsightType.FUNNELS }),
    RETENTION: urls.insightNew({ insight: InsightType.RETENTION }),
    PATHS: urls.insightNew({ insight: InsightType.PATHS }),
    JSON: urls.insightNew(undefined, undefined, JSON.stringify(examples.EventsTableFull)),
    HOG: urls.insightNew(undefined, undefined, JSON.stringify(examples.Hoggonacci)),
    SQL: urls.insightNew(undefined, undefined, JSON.stringify(examples.DataVisualization)),
}

/** Combines a list of words, separating with the correct punctuation. For example: [a, b, c, d] -> "a, b, c, and d"  */
export function concatWithPunctuation(phrases: string[]): string {
    if (phrases === null || phrases.length === 0) {
        return ''
    } else if (phrases.length === 1) {
        return phrases[0]
    } else if (phrases.length === 2) {
        return `${phrases[0]} and ${phrases[1]}`
    }
    return `${phrases.slice(0, phrases.length - 1).join(', ')}, and ${phrases[phrases.length - 1]}`
}

export function insightUrlForEvent(event: Pick<EventType, 'event' | 'properties'>): string | undefined {
    let insightParams: Partial<TrendsFilterType> | undefined
    if (event.event === '$pageview') {
        insightParams = {
            insight: InsightType.TRENDS,
            interval: 'day',
            display: ChartDisplayType.ActionsLineGraph,
            actions: [],
            events: [
                {
                    id: '$pageview',
                    name: '$pageview',
                    type: 'events',
                    order: 0,
                    properties: [
                        {
                            key: '$current_url',
                            value: event.properties.$current_url,
                            type: 'event',
                        },
                    ],
                },
            ],
        }
    } else if (event.event !== '$autocapture') {
        insightParams = {
            insight: InsightType.TRENDS,
            interval: 'day',
            display: ChartDisplayType.ActionsLineGraph,
            actions: [],
            events: [
                {
                    id: event.event,
                    name: event.event,
                    type: 'events',
                    order: 0,
                    properties: [],
                },
            ],
        }
    }

    return insightParams ? urls.insightNew(insightParams) : undefined
}
