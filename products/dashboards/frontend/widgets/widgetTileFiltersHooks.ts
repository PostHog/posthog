import { useCallback, useEffect, useRef } from 'react'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

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
    onUpdateConfig?: (config: Record<string, unknown>) => void | Promise<void>,
    receivedConfig?: Record<string, unknown>
): {
    getLatestConfig: () => Record<string, unknown>
    persistConfigDebounced: (config: Record<string, unknown>) => void
    persistConfigNow: (config: Record<string, unknown>) => Promise<void>
} {
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const debouncedConfigRef = useRef<Record<string, unknown> | null>(null)
    const latestConfigRef = useRef<Record<string, unknown>>(receivedConfig ?? {})
    const receivedConfigRef = useRef(receivedConfig)
    const pendingPersistCountRef = useRef(0)
    const persistQueueRef = useRef<Promise<void>>(Promise.resolve())
    const onUpdateConfigRef = useRef(onUpdateConfig)
    onUpdateConfigRef.current = onUpdateConfig

    if (receivedConfig !== receivedConfigRef.current) {
        receivedConfigRef.current = receivedConfig
        if (!debounceRef.current && pendingPersistCountRef.current === 0 && receivedConfig) {
            latestConfigRef.current = receivedConfig
        }
    }

    const getLatestConfig = useCallback((): Record<string, unknown> => latestConfigRef.current, [])

    const persistConfigNow = useCallback(async (config: Record<string, unknown>): Promise<void> => {
        if (debounceRef.current) {
            clearTimeout(debounceRef.current)
            debounceRef.current = null
            debouncedConfigRef.current = null
        }
        latestConfigRef.current = config
        pendingPersistCountRef.current += 1
        const persistPromise = persistQueueRef.current
            .catch(() => undefined)
            .then(() => onUpdateConfigRef.current?.(config))
        persistQueueRef.current = persistPromise
        try {
            await persistPromise
        } catch (error) {
            if (receivedConfigRef.current && latestConfigRef.current === config) {
                latestConfigRef.current = receivedConfigRef.current
            }
            if (
                error instanceof Error &&
                error.name === 'WidgetConfigValidationError' &&
                'fieldErrors' in error &&
                typeof error.fieldErrors === 'object' &&
                error.fieldErrors !== null
            ) {
                const fieldErrors = error.fieldErrors as Record<string, string | undefined>
                const validationMessage = Object.values(fieldErrors).find((message) => !!message)
                lemonToast.error(
                    validationMessage ?? 'Could not update widget filters. Check the values and try again.'
                )
            }
        } finally {
            pendingPersistCountRef.current -= 1
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
            latestConfigRef.current = config
            debouncedConfigRef.current = config
            debounceRef.current = setTimeout(() => {
                debounceRef.current = null
                debouncedConfigRef.current = null
                void persistConfigNow(config)
            }, WIDGET_TILE_REFRESH_DEBOUNCE_MS)
        },
        [persistConfigNow]
    )

    useEffect(() => {
        return () => {
            if (debounceRef.current) {
                clearTimeout(debounceRef.current)
                debounceRef.current = null
            }
            if (debouncedConfigRef.current) {
                const pendingConfig = debouncedConfigRef.current
                debouncedConfigRef.current = null
                void persistConfigNow(pendingConfig)
            }
        }
    }, [persistConfigNow])

    return { getLatestConfig, persistConfigDebounced, persistConfigNow }
}
