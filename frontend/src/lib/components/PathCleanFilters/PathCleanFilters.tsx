import { PathCleaningFilter } from '~/types'

import { PathCleanFilterAddItemButton } from './PathCleanFilterAddItemButton'
import { PathCleanFiltersTable } from './PathCleanFiltersTable'

export interface PathCleanFiltersProps {
    filters?: PathCleaningFilter[]
    setFilters: (filters: PathCleaningFilter[]) => void
}

export const keyFromFilter = (filter: PathCleaningFilter): string => {
    return `${filter.alias}-${filter.regex}`
}

export function PathCleanFilters({ filters = [], setFilters }: PathCleanFiltersProps): JSX.Element {
    const onAddFilter = (filter: PathCleaningFilter): void => {
        setFilters([...filters, filter])
    }

    return (
        <div className="flex flex-col gap-4">
            <PathCleanFiltersTable filters={filters} setFilters={setFilters} />
            <div>
                <PathCleanFilterAddItemButton onAdd={onAddFilter} />
            </div>
        </div>
    )
}
