import { buildDisplayOptions, BuildDisplayOptionsSettings } from './buildDisplayOptions'
import type { DisplayOptionBindings, DisplayOptionTab } from './displayOptions'

// What one surface (the insight Options panel, the SQL editor's Display tab) supplies: how to read its
// state, and for each option it supports, when the option shows and how it reads and saves.
export interface DisplayOptionsAdapter<C> {
    useDisplayContext: () => C
    bindings: DisplayOptionBindings<C>
    settings?: (c: C) => BuildDisplayOptionsSettings
}

export function useDisplayOptions<C>(adapter: DisplayOptionsAdapter<C>): { tabs: DisplayOptionTab[]; count: number } {
    const context = adapter.useDisplayContext()
    return buildDisplayOptions(adapter.bindings, context, adapter.settings?.(context))
}
