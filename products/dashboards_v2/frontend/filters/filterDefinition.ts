import type { ComponentType } from 'react'

import type { DashboardFilter } from '../dashboard/dashboardTypes'
import type { FilterSpec } from './filterSpec'

export const INCOMPLETE_LABEL = 'Pick a value'

export function summarizeValues(values: string[]): string {
    return values.length > 1 ? `${values[0]} +${values.length - 1}` : (values[0] ?? '')
}

export interface FilterControlProps<Config = unknown, Value = unknown> {
    filter: DashboardFilter<Config>
    value: Value | undefined
    onChange: (value: Value | undefined) => void
    /** Set on a filter the person just added, so its picker opens and picking a value is the next step. */
    defaultOpen?: boolean
}

export interface FilterDefinition<Config = unknown, Value = unknown> extends FilterSpec<Config> {
    Control: ComponentType<FilterControlProps<Config, Value>>
    Picker?: ComponentType<FilterPickerProps<Config>>
}

export interface FilterPickerProps<Config = unknown> {
    onPick: (filter: Omit<DashboardFilter<Config>, 'id'>) => void
    onClose: () => void
}

/**
 * Puts a kind of filter with its own config and value types into a list of kinds. A filter is rendered only with the
 * definition of its own type, so the control always gets the config and value it declares.
 */
export function defineFilter<Config, Value>(definition: FilterDefinition<Config, Value>): FilterDefinition {
    return definition as unknown as FilterDefinition
}
