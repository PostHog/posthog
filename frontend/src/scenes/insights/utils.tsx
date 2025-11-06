import isEqual from 'lodash.isequal'
import { ReactNode } from 'react'

import { IconWarning } from '@posthog/icons'
import { LemonButtonProps } from '@posthog/lemon-ui'

import api from 'lib/api'
import { DataColorTheme, DataColorToken } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { ensureStringIsNotBlank, humanFriendlyNumber, isEmptyObject, isObject, objectsEqual } from 'lib/utils'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { IndexedTrendResult } from 'scenes/trends/types'
import { urls } from 'scenes/urls'

import { propertyFilterTypeToPropertyDefinitionType } from '~/lib/components/PropertyFilters/utils'
import { removeUndefinedAndNull } from '~/lib/utils'
import { FormatPropertyValueForDisplayFunction } from '~/models/propertyDefinitionsModel'
import { examples } from '~/queries/examples'
import {
    ActionsNode,
    BreakdownFilter,
    DashboardFilter,
    DataWarehouseNode,
    EventsNode,
    FileSystemIconType,
    HogQLQuery,
    HogQLVariable,
    InsightVizNode,
    Node,
    NodeKind,
    PathsFilter,
    ResultCustomization,
    ResultCustomizationBy,
    ResultCustomizationByPosition,
    ResultCustomizationByValue,
} from '~/queries/schema/schema-general'
import {
    containsHogQLQuery,
    isDataTableNode,
    isDataWarehouseNode,
    isEventsNode,
    isInsightVizNode,
} from '~/queries/utils'
import { cleanInsightQuery } from '~/scenes/insights/utils/queryUtils'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from '~/taxonomy/taxonomy'
import {
    ActionFilter,
    AnyPartialFilterType,
    BreakdownKeyType,
    ChartDisplayType,
    CohortType,
    EntityFilter,
    EntityTypes,
    EventType,
    FlattenedFunnelStepByBreakdown,
    FunnelStepWithConversionMetrics,
    GroupTypeIndex,
    InsightShortId,
    InsightType,
    PathType,
    PropertyFilterType,
    PropertyOperator,
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
                        Object.assign(changedKeys, extractObjectDiffKeys(oldValue[idx], event, `event_${idx}_`))
                    })
                }
            } else if (key === 'actions') {
                const actions = valueOrArray as Record<string, any>[]
                if (actions.length !== oldValue.length) {
                    changedKeys['changed_actions_length'] = oldValue.length
                } else {
                    actions.forEach((action, idx) => {
                        Object.assign(changedKeys, extractObjectDiffKeys(oldValue[idx], action, `action_${idx}_`))
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
    const insightId = insightLogic.findMounted({ dashboardItemId: shortId })?.values?.insight?.id

    return insightId
        ? insightId
        : (await api.get(`api/environments/${getCurrentTeamId()}/insights/?short_id=${encodeURIComponent(shortId)}`))
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
            humanEventTypes.push('SQL expression')
        }
    }
    return humanEventTypes
}

export function formatAggregationValue(
    property: string | undefined | null,
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

export function isNullBreakdown(breakdown_value: string | number | bigint | null | undefined): boolean {
    return (
        breakdown_value === BREAKDOWN_NULL_STRING_LABEL ||
        breakdown_value === BREAKDOWN_NULL_NUMERIC_LABEL ||
        String(breakdown_value) === String(BREAKDOWN_NULL_NUMERIC_LABEL)
    )
}

function isValidJsonArray(maybeJson: string): boolean {
    if (maybeJson.startsWith('[')) {
        try {
            const json = JSON.parse(maybeJson)
            return Array.isArray(json)
        } catch {
            return false
        }
    }

    return false
}

function formatNumericBreakdownLabel(
    breakdown_value: number | bigint,
    breakdownFilter: BreakdownFilter | null | undefined,
    formatPropertyValueForDisplay: FormatPropertyValueForDisplayFunction | undefined,
    multipleBreakdownIndex: number | undefined
): string {
    if (isOtherBreakdown(breakdown_value)) {
        return BREAKDOWN_OTHER_DISPLAY
    }

    if (isNullBreakdown(breakdown_value)) {
        return BREAKDOWN_NULL_DISPLAY
    }

    if (formatPropertyValueForDisplay) {
        const nestedBreakdown =
            typeof multipleBreakdownIndex === 'number'
                ? breakdownFilter?.breakdowns?.[multipleBreakdownIndex]
                : undefined

        const groupIndex = (nestedBreakdown?.group_type_index ?? breakdownFilter?.breakdown_group_type_index) as
            | GroupTypeIndex
            | undefined

        return (
            formatPropertyValueForDisplay(
                nestedBreakdown?.property ?? breakdownFilter?.breakdown,
                breakdown_value,
                propertyFilterTypeToPropertyDefinitionType(nestedBreakdown?.type ?? breakdownFilter?.breakdown_type),
                groupIndex
            )?.toString() ?? 'None'
        )
    }

    return String(breakdown_value)
}

export function getCohortNameFromId(
    cohortId: string | number | null | undefined,
    cohorts: CohortType[] | null | undefined
): string {
    // :TRICKY: Different endpoints represent the all users cohort breakdown differently
    if (cohortId === 'all' || cohortId === 0) {
        return 'All Users'
    }

    return cohorts?.filter((c) => c.id == cohortId)[0]?.name ?? (cohortId || '').toString()
}

export function formatBreakdownLabel(
    breakdown_value: BreakdownKeyType | undefined,
    breakdownFilter: BreakdownFilter | null | undefined,
    cohorts: CohortType[] | undefined,
    formatPropertyValueForDisplay: FormatPropertyValueForDisplayFunction | undefined,
    multipleBreakdownIndex?: number,
    itemLabel?: string
): string {
    if (Array.isArray(breakdown_value)) {
        return breakdown_value
            .map((v, index) => formatBreakdownLabel(v, breakdownFilter, cohorts, formatPropertyValueForDisplay, index))
            .join('::')
    }

    if (typeof breakdown_value === 'string' && breakdown_value.length > 0 && isValidJsonArray(breakdown_value)) {
        // replace nan with null
        const bucketValues = breakdown_value.replace(/\bnan\b/g, 'null')
        const [bucketStart, bucketEnd] = JSON.parse(bucketValues)
        const formattedBucketStart = formatBreakdownLabel(
            bucketStart,
            breakdownFilter,
            cohorts,
            formatPropertyValueForDisplay,
            multipleBreakdownIndex
        )
        const formattedBucketEnd = formatBreakdownLabel(
            bucketEnd,
            breakdownFilter,
            cohorts,
            formatPropertyValueForDisplay,
            multipleBreakdownIndex
        )
        if (formattedBucketStart === formattedBucketEnd) {
            return formattedBucketStart
        }
        return `${formattedBucketStart} – ${formattedBucketEnd}`
    }

    if (breakdownFilter?.breakdown_type === 'cohort') {
        if (breakdown_value === 'all' || breakdown_value === 0) {
            return 'All Users'
        }
        if (cohorts == null || cohorts.length === 0) {
            if (itemLabel != null) {
                return itemLabel
            }
        }
        return getCohortNameFromId(breakdown_value, cohorts)
    }

    if (typeof breakdown_value == 'number') {
        return formatNumericBreakdownLabel(
            breakdown_value,
            breakdownFilter,
            formatPropertyValueForDisplay,
            multipleBreakdownIndex
        )
    }

    // stringified numbers
    if (breakdown_value && /^\d+$/.test(breakdown_value)) {
        const numericValue =
            Number.isInteger(Number(breakdown_value)) && !Number.isSafeInteger(Number(breakdown_value))
                ? BigInt(breakdown_value)
                : Number(breakdown_value)
        return formatNumericBreakdownLabel(
            numericValue,
            breakdownFilter,
            formatPropertyValueForDisplay,
            multipleBreakdownIndex
        )
    }

    if (typeof breakdown_value == 'string') {
        return isOtherBreakdown(breakdown_value) || breakdown_value === 'nan'
            ? BREAKDOWN_OTHER_DISPLAY
            : isNullBreakdown(breakdown_value) || breakdown_value === ''
              ? BREAKDOWN_NULL_DISPLAY
              : breakdown_value
    }

    return ''
}

export function formatBreakdownType(breakdownFilter: BreakdownFilter): string {
    if (breakdownFilter.breakdown_type === 'cohort') {
        return 'Cohort'
    }
    return breakdownFilter?.breakdown?.toString() || 'Breakdown Value'
}

export function sortCohorts(
    cohortIdA: string | number | null | undefined,
    cohortIdB: string | number | null | undefined,
    cohorts: CohortType[] | null | undefined
): number {
    const nameA = getCohortNameFromId(cohortIdA, cohorts)
    const nameB = getCohortNameFromId(cohortIdB, cohorts)
    return nameA.localeCompare(nameB)
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

export const INSIGHT_TYPE_URLS = {
    TRENDS: urls.insightNew({ type: InsightType.TRENDS }),
    STICKINESS: urls.insightNew({ type: InsightType.STICKINESS }),
    LIFECYCLE: urls.insightNew({ type: InsightType.LIFECYCLE }),
    FUNNELS: urls.insightNew({ type: InsightType.FUNNELS }),
    RETENTION: urls.insightNew({ type: InsightType.RETENTION }),
    PATHS: urls.insightNew({ type: InsightType.PATHS }),
    JSON: urls.insightNew({ query: examples.EventsTableFull }),
    HOG: urls.insightNew({ query: examples.Hoggonacci }),
    SQL: urls.sqlEditor((examples.HogQLForDataVisualization as HogQLQuery)['query']),
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
    let query: InsightVizNode | undefined
    if (event.event === '$pageview') {
        query = {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                interval: 'day',
                series: [
                    {
                        event: '$pageview',
                        name: '$pageview',
                        kind: NodeKind.EventsNode,
                        properties: [
                            {
                                key: '$current_url',
                                value: event.properties.$current_url,
                                type: PropertyFilterType.Event,
                                operator: PropertyOperator.Exact,
                            },
                        ],
                    },
                ],
                trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
            },
        }
    } else if (event.event !== '$autocapture') {
        query = {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                interval: 'day',
                series: [
                    {
                        event: event.event,
                        name: event.event,
                        kind: NodeKind.EventsNode,
                    },
                ],
                trendsFilter: { display: ChartDisplayType.ActionsLineGraph },
            },
        }
    }

    return query ? urls.insightNew({ query }) : undefined
}

export function getFunnelDatasetKey(dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics): string {
    const breakdown_value =
        Array.isArray(dataset.breakdown_value) && dataset.breakdown_value.length == 1
            ? dataset.breakdown_value[0]
            : dataset.breakdown_value
    const payload = { breakdown_value }

    return JSON.stringify(payload)
}

export function getTrendDatasetKey(dataset: IndexedTrendResult): string {
    const payload = {
        series: Number.isInteger(dataset.action?.order)
            ? dataset.action?.order
            : dataset.seriesIndex > 0
              ? `formula${dataset.seriesIndex + 1}`
              : 'formula',
        breakdown_value:
            dataset.breakdown_value !== undefined && !Array.isArray(dataset.breakdown_value)
                ? [dataset.breakdown_value]
                : dataset.breakdown_value,
        compare_label: dataset.compare_label,
    }

    return JSON.stringify(payload)
}

export function getTrendDatasetPosition(dataset: IndexedTrendResult): number {
    return dataset.seriesIndex ?? dataset.colorIndex ?? ((dataset as any).index as number)
}

/** Type guard to determine wether we have a FunnelStepWithConversionMetrics or a FlattenedFunnelStepByBreakdown */
function isFunnelStepWithConversionMetrics(
    dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics
): dataset is FunnelStepWithConversionMetrics {
    return (dataset as FlattenedFunnelStepByBreakdown).breakdownIndex == null
}

export function getFunnelDatasetPosition(
    dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics,
    disableFunnelBreakdownBaseline?: boolean
): number {
    if (isFunnelStepWithConversionMetrics(dataset)) {
        // increment the minimum order for funnels where there baseline is hidden
        // i.e. funnels for experiments where only the respective variants matter
        return disableFunnelBreakdownBaseline ? (dataset.order ?? 0) + 1 : (dataset.order ?? 0)
    }

    return dataset?.breakdownIndex ?? 0
}

export function getTrendResultCustomizationKey(
    resultCustomizationBy: ResultCustomizationBy | null | undefined,
    dataset: IndexedTrendResult
): string {
    const assignmentByValue = resultCustomizationBy == null || resultCustomizationBy === ResultCustomizationBy.Value
    return assignmentByValue ? getTrendDatasetKey(dataset) : getTrendDatasetPosition(dataset).toString()
}

export function getTrendResultCustomization(
    resultCustomizationBy: ResultCustomizationBy | null | undefined,
    dataset: IndexedTrendResult,
    resultCustomizations:
        | Record<string, ResultCustomizationByValue>
        | Record<number, ResultCustomizationByPosition>
        | null
        | undefined
): ResultCustomization | undefined {
    const resultCustomizationKey = getTrendResultCustomizationKey(resultCustomizationBy, dataset)
    return resultCustomizations && Object.keys(resultCustomizations).includes(resultCustomizationKey)
        ? (resultCustomizations as any)[resultCustomizationKey]
        : undefined
}

export function getFunnelResultCustomization(
    dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics,
    resultCustomizations: Record<string, ResultCustomizationByValue> | null | undefined
): ResultCustomization | undefined {
    const resultCustomizationKey = getFunnelDatasetKey(dataset)
    return resultCustomizations && Object.keys(resultCustomizations).includes(resultCustomizationKey)
        ? resultCustomizations[resultCustomizationKey]
        : undefined
}

export function getTrendResultCustomizationColorToken(
    resultCustomizationBy: ResultCustomizationBy | null | undefined,
    resultCustomizations:
        | Record<string, ResultCustomizationByValue>
        | Record<number, ResultCustomizationByPosition>
        | null
        | undefined,
    theme: DataColorTheme,
    dataset: IndexedTrendResult
): DataColorToken {
    const resultCustomization = getTrendResultCustomization(resultCustomizationBy, dataset, resultCustomizations)

    // for result customizations without a configuration, the color is determined
    // by the position in the dataset. colors repeat after all options
    // have been exhausted.
    // For comparison data (current vs previous periods), use colorIndex to ensure
    // they get the same base color when customizing by value
    const isValueBasedCustomization = !resultCustomizationBy || resultCustomizationBy === ResultCustomizationBy.Value
    const datasetPosition =
        isValueBasedCustomization && dataset.colorIndex !== undefined
            ? dataset.colorIndex
            : getTrendDatasetPosition(dataset)
    const tokenIndex = (datasetPosition % Object.keys(theme).length) + 1

    return resultCustomization && resultCustomization.color
        ? resultCustomization.color
        : (`preset-${tokenIndex}` as DataColorToken)
}

export function getFunnelResultCustomizationColorToken(
    resultCustomizations: Record<string, ResultCustomizationByValue> | null | undefined,
    theme: DataColorTheme,
    dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics,
    disableFunnelBreakdownBaseline?: boolean
): DataColorToken {
    const resultCustomization = getFunnelResultCustomization(dataset, resultCustomizations)

    const datasetPosition = getFunnelDatasetPosition(dataset, disableFunnelBreakdownBaseline)
    const tokenIndex = (datasetPosition % Object.keys(theme).length) + 1

    return resultCustomization && resultCustomization.color
        ? resultCustomization.color
        : (`preset-${tokenIndex}` as DataColorToken)
}

export function isQueryTooLarge(query: Node<Record<string, any>>): boolean {
    // Chrome has a 2MB limit for the HASH params, limit ours at 1MB
    const queryLength = encodeURI(JSON.stringify(query)).split(/%..|./).length - 1
    return queryLength > 1024 * 1024
}

function parseQuery<T>(query: string): T | null {
    try {
        return JSON.parse(query)
    } catch (e) {
        console.error('Error parsing query', e)
        return null
    }
}

export function parseDraftQueryFromLocalStorage(
    query: string
): { query: Node<Record<string, any>>; timestamp: number } | null {
    return parseQuery(query)
}

export function crushDraftQueryForLocalStorage(query: Node<Record<string, any>>, timestamp: number): string {
    return JSON.stringify({ query, timestamp })
}

export function parseDraftQueryFromURL(query: string): Node<Record<string, any>> | null {
    return parseQuery(query)
}

export function crushDraftQueryForURL(query: Node<Record<string, any>>): string {
    return JSON.stringify(query)
}

const SOURCE_FIELD_LABELS: Record<string, string> = {
    breakdownFilter: 'Breakdowns',
    compareFilter: 'Compare filter',
    dateRange: 'Date range',
    filterTestAccounts: 'Test account filtering',
    interval: 'Interval',
    kind: 'Insight type',
    properties: 'Global property filters',
    samplingFactor: 'Sampling',
    series: 'Series',
    trendsFilter: 'Display options',
}

function arraysEqual(arr1: any[], arr2: any[]): boolean {
    if (arr1.length !== arr2.length) {
        return false
    }

    // Create copies and sort them for order-independent comparison
    const sorted1 = [...arr1].sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)))
    const sorted2 = [...arr2].sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)))

    // Compare each element
    for (let i = 0; i < sorted1.length; i++) {
        if (!isEqual(sorted1[i], sorted2[i])) {
            return false
        }
    }
    return true
}

function deepEqual(val1: any, val2: any): boolean {
    if (Array.isArray(val1) && Array.isArray(val2)) {
        return arraysEqual(val1, val2)
    }
    return isEqual(val1, val2)
}

export function compareInsightTopLevelSections(obj1: any, obj2: any): string[] {
    const changedLabels = new Set<string>()

    const cleanObj1 = cleanInsightQuery(removeUndefinedAndNull(obj1)) as Record<string, any>
    const cleanObj2 = cleanInsightQuery(removeUndefinedAndNull(obj2)) as Record<string, any>

    // Handle both InsightVizNode (with source) and InsightQueryNode (without source)
    const source1 = cleanObj1.source || cleanObj1
    const source2 = cleanObj2.source || cleanObj2

    if (!objectsEqual(source1, source2)) {
        const keys = new Set([...Object.keys(source1 || {}), ...Object.keys(source2 || {})])

        for (const key of keys) {
            const val1 = source1?.[key]
            const val2 = source2?.[key]

            // Check if the property exists in both objects and has different values
            // Also check if property exists in one but not the other
            if (!deepEqual(val1, val2) || key in source1 !== key in source2) {
                const label = SOURCE_FIELD_LABELS[key] || key
                changedLabels.add(label)
            }
        }
    }

    return Array.from(changedLabels).sort()
}

export function getInsightIconTypeFromQuery(query: any): FileSystemIconType {
    if (!query?.kind) {
        return 'product_analytics'
    }

    let nodeKind: NodeKind
    if ((isDataTableNode(query) && containsHogQLQuery(query)) || isInsightVizNode(query)) {
        nodeKind = query.source.kind
    } else {
        nodeKind = query.kind
    }

    // Map NodeKind to the fileSystemType color names
    const nodeKindToColor: Partial<Record<NodeKind, FileSystemIconType>> = {
        [NodeKind.TrendsQuery]: 'insight/trends',
        [NodeKind.FunnelsQuery]: 'insight/funnels',
        [NodeKind.RetentionQuery]: 'insight/retention',
        [NodeKind.PathsQuery]: 'insight/paths',
        [NodeKind.StickinessQuery]: 'insight/stickiness',
        [NodeKind.LifecycleQuery]: 'insight/lifecycle',
        [NodeKind.HogQuery]: 'insight/hog',
        [NodeKind.HogQLQuery]: 'insight/hog',
        [NodeKind.DataVisualizationNode]: 'insight/hog',
        [NodeKind.DataTableNode]: 'insight/hog',
    }

    const mappedIconType: FileSystemIconType = nodeKindToColor[nodeKind] || 'product_analytics'

    return mappedIconType
}

export const getOverrideWarningPropsForButton = (
    filtersOverride: DashboardFilter | null | undefined,
    variablesOverride: Record<string, HogQLVariable> | null | undefined
): Pick<LemonButtonProps, 'icon' | 'tooltip'> => {
    const filterOverridesExist =
        isObject(filtersOverride) &&
        Object.values(filtersOverride).some(
            (value) => value !== null && (!Array.isArray(value) || value.length > 0)
        )
    const variableOverridesExist = isObject(variablesOverride) && !isEmptyObject(variablesOverride)

    const overrideType =
        filterOverridesExist && variableOverridesExist ? 'overrides' : filterOverridesExist ? 'filters' : 'variables'

    return filterOverridesExist || variableOverridesExist
        ? {
              icon: <IconWarning />,
              tooltip: `This insight is being viewed with dashboard ${overrideType}. These will be discarded on edit.`,
          }
        : {}
}
