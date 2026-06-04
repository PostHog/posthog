import { useCallback, useEffect, useRef, useState } from 'react'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import type { QuickFilter } from '~/types'

import { WIDGET_TILE_REFRESH_DEBOUNCE_MS } from './constants'
import { isAllowedErrorTrackingWidgetFilter } from './error_tracking/constants'
import { isAllowedSessionReplayWidgetFilter } from './session_replay/constants'

export type WidgetFilterDefinitionsSetup = {
    /** Loads saved property-filter definitions for tile pickers (project Quick Filter records). */
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
    onUpdateConfigRef.current = onUpdateConfig

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

    return { persistConfigDebounced, persistConfigNow, isPersisting }
}
