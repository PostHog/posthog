import { useCallback, useEffect, useRef, useState } from 'react'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType, type QuickFilter, type UniversalFiltersGroup } from '~/types'

import type { WidgetFilterConfigRecord } from '../widget_types/configSchemas'
import {
    ERROR_TRACKING_WIDGET_FILTER_DISPLAY_NAMES,
    isAllowedErrorTrackingWidgetFilter,
} from './error_tracking/constants'
import { isAllowedSessionReplayWidgetFilter } from './session_replay/constants'

const TILE_FILTER_CONFIG_DEBOUNCE_MS = 300

export type WidgetFilterDefinitionsSetup = {
    /** Loads filter definitions (options/labels) for tile property pickers. */
    context: QuickFilterContext
    isAllowed: (filter: Pick<QuickFilter, 'name' | 'property_name'>) => boolean
}

export const sessionReplayWidgetFiltersSetup: WidgetFilterDefinitionsSetup = {
    context: QuickFilterContext.Dashboards,
    isAllowed: isAllowedSessionReplayWidgetFilter,
}

export const errorTrackingWidgetFiltersSetup: WidgetFilterDefinitionsSetup = {
    context: QuickFilterContext.ErrorTrackingIssueFilters,
    isAllowed: isAllowedErrorTrackingWidgetFilter,
}

export const ERROR_TRACKING_WIDGET_FILTER_ALLOWED_DISPLAY_NAMES = ERROR_TRACKING_WIDGET_FILTER_DISPLAY_NAMES.join(', ')

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

export function getAllowedWidgetFilterDefinitions(
    filterDefinitions: QuickFilter[],
    isAllowed: (filter: QuickFilter) => boolean
): QuickFilter[] {
    return filterDefinitions.filter(isAllowed)
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
