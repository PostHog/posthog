import { type ComponentType, useCallback, useMemo, useState } from 'react'

import type { FilterBarProps } from './FilterBar'
import type { FilterDefinition } from './filterDefinition'

export interface FiltersController {
    types: FilterDefinition[]
    values: Record<string, unknown>
    onValueChange: (id: string, value: unknown) => void
    /** Replaces the default `FilterBar`, such as a bar built from `FilterPill` with no overflow or no add menu. */
    Bar?: ComponentType<FilterBarProps>
}

/**
 * Keeps each viewer's picked values in component state, for a host with nowhere else to keep them. A host that keeps
 * them in the URL or its own logic builds a `FiltersController` itself instead.
 */
export function useFiltersController(
    types: FilterDefinition[],
    Bar?: ComponentType<FilterBarProps>
): FiltersController {
    const [values, setValues] = useState<Record<string, unknown>>({})
    const onValueChange = useCallback((id: string, value: unknown) => {
        setValues((state) => {
            const { [id]: _, ...rest } = state
            return value === undefined ? rest : { ...rest, [id]: value }
        })
    }, [])
    return useMemo(() => ({ types, values, onValueChange, Bar }), [types, values, onValueChange, Bar])
}
