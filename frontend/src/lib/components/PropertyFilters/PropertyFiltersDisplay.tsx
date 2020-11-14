import React from 'react'
import { PropertyFilter } from '~/types'
import PropertyFilterButton from './PropertyFilterButton'

type Props = {
    filters: PropertyFilter[]
}

const PropertyFiltersDisplay = ({ filters }: Props) => {
    return (
        <div className="mb">
            {filters &&
                filters.map((item) => {
                    return <PropertyFilterButton item={item} />
                })}
        </div>
    )
}

export default PropertyFiltersDisplay
