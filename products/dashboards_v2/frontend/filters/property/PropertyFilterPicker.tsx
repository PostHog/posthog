import type { FilterPickerProps } from '../filterDefinition'
import { FieldSearch } from '../pickers/FieldSearch'
import { type FeaturedProperty, PROPERTY_FILTER_TYPE, type PropertyFilterConfig } from './propertyFilterSpec'

export type PropertySearch = {
    label: string
    load: (search: string, signal: AbortSignal) => Promise<FeaturedProperty[]>
}

export function PropertyFilterPicker({
    search,
    onPick,
}: FilterPickerProps<PropertyFilterConfig> & { search: PropertySearch }): JSX.Element {
    return (
        <FieldSearch
            load={search.load}
            placeholder="Search properties"
            onPick={({ key, label, source = 'event' }) =>
                onPick({ type: PROPERTY_FILTER_TYPE, label, config: { key, source } })
            }
        />
    )
}
