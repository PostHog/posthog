import { AnyPropertyFilter } from '~/types'

import { PropertyFilterButton } from './PropertyFilterButton'

const PropertyFiltersDisplay = ({
    filters,
    compact = false,
}: {
    filters: AnyPropertyFilter[]
    compact?: boolean
}): JSX.Element => {
    return (
        <div className="PropertyFilters flex-wrap">
            {filters &&
                filters.map((item) => {
                    return <PropertyFilterButton key={item.key} item={item} compact={compact} />
                })}
        </div>
    )
}

export default PropertyFiltersDisplay
