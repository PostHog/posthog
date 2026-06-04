import { useCallback, useEffect, useRef, useState } from 'react'

import type { SelectedQuickFilter } from 'lib/components/QuickFilters/quickFiltersSectionLogic'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType, type QuickFilter, type UniversalFiltersGroup } from '~/types'

import type {
    StoredWidgetFilter,
    WidgetFilterConfigEntry,
    WidgetFilterConfigRecord,
} from '../widget_types/configSchemas'
import {
    ERROR_TRACKING_WIDGET_QUICK_FILTER_DISPLAY_NAMES,
    EDIT_ERROR_TRACKING_WIDGET_FILTERS_LOGIC_KEY,
    isAllowedErrorTrackingWidgetFilter,
} from './error_tracking/constants'

const TILE_FILTER_CONFIG_DEBOUNCE_MS = 300

export type WidgetFiltersEditSetup = {
    context: QuickFilterContext
    logicKey: string
    isAllowed: (filter: Pick<QuickFilter, 'name' | 'property_name'>) => boolean
    allowedDisplayNames: string
    configureLabel: string
    fieldHelp: string
    configureHref?: string
    useDashboardPathnameForConfigureHref?: boolean
    scopePickerIdsToDashboardQuickFilters?: boolean
    emptyStateFilterCategory?: string
}

export const sessionReplayWidgetFiltersSetup: WidgetFiltersEditSetup = {
    context: QuickFilterContext.Dashboards,
    logicKey: 'EditSessionReplayWidgetModal',
    isAllowed: () => true,
    allowedDisplayNames: '',
    configureLabel: 'this dashboard',
    fieldHelp: 'Filter recordings by event properties. Uses the same filters as this dashboard.',
    useDashboardPathnameForConfigureHref: true,
    scopePickerIdsToDashboardQuickFilters: true,
    emptyStateFilterCategory: 'event property filters',
}

export const errorTrackingWidgetFiltersSetup: WidgetFiltersEditSetup = {
    context: QuickFilterContext.ErrorTrackingIssueFilters,
    logicKey: EDIT_ERROR_TRACKING_WIDGET_FILTERS_LOGIC_KEY,
    isAllowed: isAllowedErrorTrackingWidgetFilter,
    allowedDisplayNames: ERROR_TRACKING_WIDGET_QUICK_FILTER_DISPLAY_NAMES.join(', '),
    configureHref: '/error_tracking',
    configureLabel: 'Error tracking Issues',
    fieldHelp: 'Filter issues by properties configured on the Error tracking Issues tab.',
}

export function useWidgetTileConfigPersist(
    onUpdateConfig?: (config: Record<string, unknown>) => void | Promise<void>
): {
    persistConfigDebounced: (config: Record<string, unknown>) => void
    persistConfigNow: (config: Record<string, unknown>) => Promise<void>
    isPersisting: boolean
} {
    const [isPersisting, setIsPersisting] = useState(false)
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const generationRef = useRef(0)
    const onUpdateConfigRef = useRef(onUpdateConfig)

    useEffect(() => {
        onUpdateConfigRef.current = onUpdateConfig
    }, [onUpdateConfig])

    const persistConfigNow = useCallback(async (config: Record<string, unknown>): Promise<void> => {
        const save = onUpdateConfigRef.current
        if (!save) {
            return
        }
        generationRef.current += 1
        const generation = generationRef.current
        setIsPersisting(true)
        try {
            await save(config)
        } finally {
            if (generation === generationRef.current) {
                setIsPersisting(false)
            }
        }
    }, [])

    const persistConfigDebounced = useCallback(
        (config: Record<string, unknown>): void => {
            if (!onUpdateConfigRef.current) {
                return
            }
            if (debounceRef.current) {
                clearTimeout(debounceRef.current)
            }
            debounceRef.current = setTimeout(() => {
                debounceRef.current = null
                void persistConfigNow(config)
            }, TILE_FILTER_CONFIG_DEBOUNCE_MS)
        },
        [persistConfigNow]
    )

    useEffect(() => {
        return () => {
            if (debounceRef.current) {
                clearTimeout(debounceRef.current)
            }
        }
    }, [])

    return { persistConfigDebounced, persistConfigNow, isPersisting }
}

export function useWidgetTileFiltersRestore({
    tileId,
    widgetFilters,
    selectedQuickFilterIds,
    restoreQuickFilterValue,
    restoreClearQuickFilter,
}: {
    tileId: number
    widgetFilters: WidgetFilterConfigRecord | undefined
    selectedQuickFilterIds: string[]
    restoreQuickFilterValue: (
        filterId: string,
        propertyName: string,
        option: {
            id: string
            value: string | string[] | null
            operator: string
            label: string
        }
    ) => void
    restoreClearQuickFilter: (filterId: string) => void
}): boolean {
    const [filtersRestored, setFiltersRestored] = useState(false)
    const widgetFiltersKey = JSON.stringify(widgetFilters ?? {})

    useEffect(() => {
        setFiltersRestored(false)
        restoreWidgetFiltersOnTileMount({
            storedWidgetFilters: widgetFilters,
            selectedQuickFilterIds,
            restoreQuickFilterValue,
            restoreClearQuickFilter,
        })
        setFiltersRestored(true)
    }, [
        tileId,
        widgetFiltersKey,
        widgetFilters,
        selectedQuickFilterIds,
        restoreQuickFilterValue,
        restoreClearQuickFilter,
    ])

    return filtersRestored
}

export function restoreWidgetFiltersOnTileMount({
    storedWidgetFilters,
    selectedQuickFilterIds,
    restoreQuickFilterValue,
    restoreClearQuickFilter,
}: {
    storedWidgetFilters: WidgetFilterConfigRecord | undefined
    selectedQuickFilterIds: string[]
    restoreQuickFilterValue: (
        filterId: string,
        propertyName: string,
        option: {
            id: string
            value: string | string[] | null
            operator: WidgetFilterConfigEntry['operator']
            label: string
        }
    ) => void
    restoreClearQuickFilter: (filterId: string) => void
}): void {
    restoreWidgetFiltersFromConfig(
        storedWidgetFilters ?? {},
        restoreQuickFilterValue,
        restoreClearQuickFilter,
        selectedQuickFilterIds
    )
}

export function storedWidgetFiltersFromConfig(
    widgetFilters: Record<string, StoredWidgetFilter> | undefined
): Record<string, StoredWidgetFilter> {
    return (widgetFilters ?? {}) as Record<string, StoredWidgetFilter>
}

export function getAllowedWidgetFilterIds(
    filterDefinitions: QuickFilter[],
    isAllowed: (filter: QuickFilter) => boolean
): string[] {
    return filterDefinitions.filter(isAllowed).map((filter) => filter.id)
}

export function widgetFiltersForSave(
    selectedQuickFilters: Record<string, SelectedQuickFilter>
): WidgetFilterConfigRecord {
    const entries = Object.values(selectedQuickFilters)
    if (entries.length === 0) {
        return {}
    }
    return Object.fromEntries(
        entries.map((entry) => [
            entry.filterId,
            {
                filterId: entry.filterId,
                propertyName: entry.propertyName,
                optionId: entry.optionId,
                value: entry.value,
                operator: entry.operator,
            },
        ])
    )
}

export function restoreWidgetFiltersFromConfig(
    stored: WidgetFilterConfigRecord,
    restoreQuickFilterValue: (
        filterId: string,
        propertyName: string,
        option: {
            id: string
            value: string | string[] | null
            operator: WidgetFilterConfigEntry['operator']
            label: string
        }
    ) => void,
    restoreClearQuickFilter: (filterId: string) => void,
    selectedQuickFilterIds: string[]
): void {
    selectedQuickFilterIds.forEach((filterId) => {
        restoreClearQuickFilter(filterId)
    })

    Object.values(stored).forEach((entry) => {
        restoreQuickFilterValue(entry.filterId, entry.propertyName, {
            id: entry.optionId,
            value: entry.value ?? '',
            operator: entry.operator,
            label: String(entry.value ?? ''),
        })
    })
}

/** Converts persisted widget `config.widgetFilters` into a HogQL/universal filter group. */
export function buildFilterGroupFromWidgetFilters(
    widgetFilters: WidgetFilterConfigRecord | undefined
): UniversalFiltersGroup | undefined {
    const selections = widgetFilters ? Object.values(widgetFilters) : []
    if (selections.length === 0) {
        return undefined
    }

    const filtersFromWidgetFilters = selections.map((entry) => {
        const filterValue = entry.value === null ? undefined : Array.isArray(entry.value) ? entry.value : [entry.value]

        return {
            type: PropertyFilterType.Event,
            key: entry.propertyName,
            operator: entry.operator,
            ...(filterValue !== undefined && { value: filterValue }),
        }
    })

    return {
        type: FilterLogicalOperator.And,
        values: [
            {
                type: FilterLogicalOperator.And,
                values: filtersFromWidgetFilters,
            },
        ],
    } as UniversalFiltersGroup
}
