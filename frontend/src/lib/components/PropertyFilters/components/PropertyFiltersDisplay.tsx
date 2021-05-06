import React, { CSSProperties } from 'react'
import { PropertyFilter } from '~/types'
import PropertyFilterButton from './PropertyFilterButton'

type Props = {
    filters: PropertyFilter[]
    style?: CSSProperties
}

const PropertyFiltersDisplay: React.FunctionComponent<Props> = ({ filters, style }: Props) => {
    return (
        <div className="mb" style={style}>
            {filters &&
                filters.map((item) => {
                    return <PropertyFilterButton key={item.key} item={item} />
                })}
        </div>
    )
}

export default PropertyFiltersDisplay
