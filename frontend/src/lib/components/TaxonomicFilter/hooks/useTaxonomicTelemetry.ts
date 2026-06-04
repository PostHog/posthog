/**
 * Emits the TaxonomicFilter telemetry contract from the headless rebuild so it
 * matches what the legacy kea picker emits. PostHog auto-attaches the active
 * `$feature/taxonomic-filter-headless` flag to every event, so the legacy
 * (control) and rebuild (test) arms are comparable by flag value once both
 * fire the same events with the same property shapes.
 *
 * Four of the five legacy events apply here; the fifth — `taxonomic filter
 * category dropdown opened` — is specific to the dead CategoryDropdown A/B and
 * has no analogue in the pills rebuild.
 *
 * Event ownership:
 *   - `taxonomic filter closed`        — here (mount/unmount lifecycle)
 *   - `taxonomic_filter_search_query`  — here (500ms debounce + paste tracking)
 *   - `taxonomic filter item selected` — here, via `captureItemSelected`
 *   - `taxonomic filter empty result`  — in Panel (the single active-group view)
 */
import posthog from 'posthog-js'
import { useCallback, useEffect, useRef } from 'react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

const SEARCH_QUERY_DEBOUNCE_MS = 500

export interface ItemSelectedEvent {
    groupType: TaxonomicFilterGroupType
    sourceGroupType: TaxonomicFilterGroupType
    wasFromRecents: boolean
    wasFromPinnedList: boolean
    wasQuickFilter: boolean
    hadSearchInput: boolean
    position?: number
    query?: string
    /** Extra fields for quick-filter (keyword shortcut) selections. */
    quickFilterProps?: Record<string, unknown>
}

export interface TaxonomicTelemetry {
    /** Flip the interaction flag so a `closed` event fires on unmount. Call on
     *  any genuine user action (type, tab, arrow, select). */
    markInteraction: () => void
    /** Accumulate pasted characters for the next search-query capture. */
    recordPaste: (pastedLength: number) => void
    /** Fire `taxonomic filter item selected` and record that a selection happened. */
    captureItemSelected: (event: ItemSelectedEvent) => void
}

export function useTaxonomicTelemetry({
    activeGroupType,
    searchQuery,
}: {
    activeGroupType: TaxonomicFilterGroupType
    searchQuery: string
}): TaxonomicTelemetry {
    const openedAtRef = useRef<number>(Date.now())
    const hadInteractionRef = useRef(false)
    const hadSelectionRef = useRef(false)
    const pastedCharsRef = useRef(0)
    // Read the live active tab inside the unmount cleanup / debounce timer
    // without re-running those effects when the tab changes.
    const activeGroupTypeRef = useRef(activeGroupType)
    activeGroupTypeRef.current = activeGroupType

    // `taxonomic filter closed` — fire once on unmount, but only if the user
    // actually interacted (mirrors the legacy `hadInteraction` guard that
    // suppresses phantom closes from popovers mounted before they're shown).
    useEffect(() => {
        openedAtRef.current = Date.now()
        return () => {
            if (!hadInteractionRef.current) {
                return
            }
            posthog.capture('taxonomic filter closed', {
                dwellMs: Date.now() - openedAtRef.current,
                hadSelection: hadSelectionRef.current,
                groupType: activeGroupTypeRef.current,
            })
        }
    }, [])

    // `taxonomic_filter_search_query` — debounced; only fires for a non-empty
    // query. `inputMode`/`pastedFraction` distinguish typed vs pasted input.
    useEffect(() => {
        const trimmed = searchQuery.trim()
        if (!trimmed) {
            return
        }
        const timer = setTimeout(() => {
            const pastedChars = pastedCharsRef.current
            pastedCharsRef.current = 0
            const totalLength = searchQuery.length
            const inputMode =
                pastedChars >= totalLength && pastedChars > 0 ? 'pasted' : pastedChars > 0 ? 'mixed' : 'typed'
            posthog.capture('taxonomic_filter_search_query', {
                searchQuery,
                groupType: activeGroupTypeRef.current,
                inputMode,
                pastedFraction: totalLength > 0 ? Math.min(1, pastedChars / totalLength) : 0,
            })
        }, SEARCH_QUERY_DEBOUNCE_MS)
        return () => clearTimeout(timer)
    }, [searchQuery])

    const markInteraction = useCallback(() => {
        hadInteractionRef.current = true
    }, [])

    const recordPaste = useCallback((pastedLength: number) => {
        pastedCharsRef.current += Math.max(0, pastedLength)
        hadInteractionRef.current = true
    }, [])

    const captureItemSelected = useCallback((event: ItemSelectedEvent) => {
        hadInteractionRef.current = true
        hadSelectionRef.current = true
        const { quickFilterProps, ...rest } = event
        posthog.capture('taxonomic filter item selected', {
            ...rest,
            query: rest.query || undefined,
            ...quickFilterProps,
        })
    }, [])

    return { markInteraction, recordPaste, captureItemSelected }
}
