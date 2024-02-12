import { PathCleaningFilter } from '~/types'

import { PathCleanFilterAddItemButton } from './PathCleanFilterAddItemButton'
import { PathCleanFilterItem } from './PathCleanFilterItem'

export interface PathCleanFiltersProps {
    filters?: PathCleaningFilter[]
    setFilters: (filters: PathCleaningFilter[]) => void
}

export function PathCleanFilters({ filters = [], setFilters }: PathCleanFiltersProps): JSX.Element {
    const onAddFilter = (filter: PathCleaningFilter): void => {
        setFilters([...filters, filter])
    }
    const onEditFilter = (index: number, filter: PathCleaningFilter): void => {
        const newFilters = filters.map((f, i) => {
            if (i === index) {
                return filter
            } else {
                return f
            }
        })
        setFilters(newFilters)
    }
    const onRemoveFilter = (index: number): void => {
        setFilters(filters.filter((_, i) => i !== index))
    }

    return (
        <div className="flex items-center gap-2 flex-wrap">
            {filters.map((filter, index) => (
                <PathCleanFilterItem
                    key={index}
                    filter={filter}
                    onChange={(filter) => {
                        onEditFilter(index, filter)
                    }}
                    onRemove={() => {
                        onRemoveFilter(index)
                    }}
                />
            ))}
            <PathCleanFilterAddItemButton onAdd={onAddFilter} />
        </div>
    )
}
