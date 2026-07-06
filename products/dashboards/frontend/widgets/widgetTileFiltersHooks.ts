import { useCallback, useEffect, useRef } from 'react'

import type { QuickFilter } from '~/types'

import {
    DASHBOARD_WIDGET_CATALOG,
    type DashboardWidgetCatalogEntry,
    type DashboardWidgetCatalogKey,
    type DashboardWidgetTileFiltersCatalogConfig,
} from '../widget_types/catalog'
import { WIDGET_TILE_REFRESH_DEBOUNCE_MS } from './constants'

export type WidgetFilterDefinitionsSetup = {
    /** Loads saved property-filter definitions for tile pickers (project Quick Filter records). */
    context: DashboardWidgetTileFiltersCatalogConfig['quickFilterContext']
    isAllowed: (filter: Pick<QuickFilter, 'name' | 'property_name'>) => boolean
}

export function widgetTileFiltersSetupFromCatalog(
    config: DashboardWidgetTileFiltersCatalogConfig
): WidgetFilterDefinitionsSetup {
    const allowedPropertyNames = new Set(
        config.allowedPropertyNames.map((propertyName) => propertyName.trim().toLowerCase())
    )
    return {
        context: config.quickFilterContext,
        isAllowed: (filter) => allowedPropertyNames.has(filter.property_name.trim().toLowerCase()),
    }
}

export function getWidgetTileFiltersSetup(widgetType: DashboardWidgetCatalogKey): WidgetFilterDefinitionsSetup {
    const entry: DashboardWidgetCatalogEntry = DASHBOARD_WIDGET_CATALOG[widgetType]
    const tileFilters = entry.tileFilters
    if (!tileFilters) {
        throw new Error(`Dashboard widget catalog entry ${widgetType} is missing tileFilters config`)
    }
    return widgetTileFiltersSetupFromCatalog(tileFilters)
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
