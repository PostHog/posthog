import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import {
    EventTriggerConfig,
    SessionRecordingTriggerConditions,
    SessionRecordingTriggerGroup,
    TriggerPropertyFilter,
    UrlTriggerConfig,
} from '~/lib/components/IngestionControls/types'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

/** Operators supported by the SDK for trigger property evaluation */
export const SUPPORTED_OPERATORS: PropertyOperator[] = [
    PropertyOperator.Exact,
    PropertyOperator.IsNot,
    PropertyOperator.IContains,
    PropertyOperator.NotIContains,
    PropertyOperator.Regex,
    PropertyOperator.NotRegex,
    PropertyOperator.GreaterThan,
    PropertyOperator.LessThan,
]

/** Short display labels for trigger property operators */
export const OPERATOR_DISPLAY: Record<string, string> = {
    exact: 'equals',
    is_not: 'not equals',
    icontains: 'contains',
    not_icontains: 'not contains',
    regex: 'matches regex',
    not_regex: 'not matches regex',
    gt: '>',
    lt: '<',
}

export interface ConditionRowProps {
    type: 'events' | 'urls' | 'flag'
    values: string[]
    matchType: 'any' | 'all'
    eventConfigs?: EventTriggerConfig[]
}

/** Convert our trigger property filters to the AnyPropertyFilter format PropertyFilters component expects */
export function triggerFiltersToPropertyFilters(filters: TriggerPropertyFilter[]): AnyPropertyFilter[] {
    return filters.map(
        (f) =>
            ({
                key: f.key,
                type: f.type === 'person' ? PropertyFilterType.Person : PropertyFilterType.Event,
                operator: (f.operator as PropertyOperator) || PropertyOperator.Exact,
                value: f.value ?? '',
            }) as AnyPropertyFilter
    )
}

/** Convert PropertyFilters output back to our trigger property filter format */
export function propertyFiltersToTriggerFilters(filters: AnyPropertyFilter[]): TriggerPropertyFilter[] {
    return filters
        .filter((f) => f.key)
        .map((f) => ({
            key: f.key!,
            type: f.type === PropertyFilterType.Person ? ('person' as const) : ('event' as const),
            operator: 'operator' in f ? (f.operator as TriggerPropertyFilter['operator']) : 'exact',
            value: 'value' in f ? (f.value as TriggerPropertyFilter['value']) : undefined,
        }))
}

export function triggerGroupDisplayName(name: string | undefined, id: string | null | undefined): string {
    return name || `Trigger group ${id?.slice(0, 8)}`
}

export function confirmDeleteTriggerGroup(
    triggerGroups: SessionRecordingTriggerGroup[],
    id: string,
    setDeleteModalGroupId: (id: string | null) => void,
    deleteTriggerGroup: (id: string) => void
): void {
    if (triggerGroups.length === 1) {
        setDeleteModalGroupId(id)
    } else {
        // Standard confirmation for non-last groups
        const group = triggerGroups.find((g) => g.id === id)
        const displayName = triggerGroupDisplayName(group?.name, id)

        LemonDialog.open({
            title: 'Delete trigger group?',
            description: `Are you sure you want to delete "${displayName}"? This cannot be undone.`,
            primaryButton: {
                children: 'Delete',
                status: 'danger',
                onClick: () => deleteTriggerGroup(id),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }
}

export function withAddedEvents(existing: EventTriggerConfig[], events: string[]): EventTriggerConfig[] {
    const existingNames = new Set(existing.map((e) => e.name))
    const newEvents = events.filter((name) => !existingNames.has(name)).map((name) => ({ name }))

    return [...existing, ...newEvents]
}

export function urlMatchesAnyPattern(urls: UrlTriggerConfig[], testUrl: string): boolean {
    return urls.some((urlConfig) => {
        try {
            const regex = new RegExp(urlConfig.url)
            return regex.test(testUrl)
        } catch {
            return false
        }
    })
}

// Build condition rows - group same types together
export function buildConditionRows(conditions: SessionRecordingTriggerConditions): ConditionRowProps[] {
    const conditionRows: ConditionRowProps[] = []

    if (conditions.events && conditions.events.length > 0) {
        const eventValues = conditions.events.map((e) => (typeof e === 'string' ? e : e.name))
        const eventConfigs = conditions.events.map((e): EventTriggerConfig => (typeof e === 'string' ? { name: e } : e))
        conditionRows.push({
            type: 'events',
            values: eventValues,
            matchType: conditions.matchType,
            eventConfigs,
        })
    }

    if (conditions.urls && conditions.urls.length > 0) {
        conditionRows.push({
            type: 'urls',
            values: conditions.urls.map((urlConfig) => urlConfig.url),
            matchType: conditions.matchType,
        })
    }

    if (conditions.flag) {
        const flagKey = typeof conditions.flag === 'string' ? conditions.flag : conditions.flag.key
        conditionRows.push({
            type: 'flag',
            values: [flagKey],
            matchType: conditions.matchType,
        })
    }

    return conditionRows
}
