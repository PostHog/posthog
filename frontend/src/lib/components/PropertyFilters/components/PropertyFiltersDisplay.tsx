import { AnyPropertyFilter } from '~/types'

import { PropertyFilterButton } from './PropertyFilterButton'

const PropertyFiltersDisplay = ({ filters }: { filters: AnyPropertyFilter[] }): JSX.Element => {
    return (
        <div className="PropertyFilters flex-wrap">
            {filters &&
                filters.map((item) => {
                    return <PropertyFilterButton key={item.key} item={item} />
                })}
        </div>
    )
}

export default PropertyFiltersDisplay
