import { useCallback, useEffect, useRef } from 'react'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import type { QuickFilter } from '~/types'

import { WIDGET_TILE_REFRESH_DEBOUNCE_MS } from './constants'
import { isAllowedErrorTrackingWidgetFilter } from './error_tracking/constants'

const SESSION_REPLAY_WIDGET_FILTER_PROPERTY_NAMES = new Set([
    '$browser',
    '$os',
    '$device_type',
    '$geoip_country_code',
    '$geoip_city_name',
    '$current_url',
    '$pathname',
    '$host',
    '$referring_domain',
    '$lib',
])

export type WidgetFilterDefinitionsSetup = {
    /** Loads saved property-filter definitions for tile pickers (project Quick Filter records). */
    context: QuickFilterContext
    isAllowed: (filter: Pick<QuickFilter, 'name' | 'property_name'>) => boolean
}

export const sessionReplayWidgetFiltersSetup: WidgetFilterDefinitionsSetup = {
    context: QuickFilterContext.Dashboards,
    isAllowed: (filter) => SESSION_REPLAY_WIDGET_FILTER_PROPERTY_NAMES.has(filter.property_name.trim().toLowerCase()),
}

export const errorTrackingWidgetFiltersSetup: WidgetFilterDefinitionsSetup = {
    context: QuickFilterContext.ErrorTrackingIssueFilters,
    isAllowed: isAllowedErrorTrackingWidgetFilter,
}

export function useWidgetTileConfigPersist(
    onUpdateConfig?: (config: Record<string, unknown>) => void | Promise<void>
): {
    persistConfigDebounced: (config: Record<string, unknown>) => void
    persistConfigNow: (config: Record<string, unknown>) => Promise<void>
} {
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const onUpdateConfigRef = useRef(onUpdateConfig)
    onUpdateConfigRef.current = onUpdateConfig

    const persistConfigNow = useCallback(async (config: Record<string, unknown>): Promise<void> => {
        if (debounceRef.current) {
            clearTimeout(debounceRef.current)
            debounceRef.current = null
        }
        await onUpdateConfigRef.current?.(config)
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
            }, WIDGET_TILE_REFRESH_DEBOUNCE_MS)
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

    return { persistConfigDebounced, persistConfigNow }
}
