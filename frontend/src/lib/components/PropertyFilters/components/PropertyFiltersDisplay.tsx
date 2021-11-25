import React, { CSSProperties } from 'react'
import { AnyPropertyFilter } from '~/types'
import PropertyFilterButton from './PropertyFilterButton'

type Props = {
    filters: AnyPropertyFilter[]
    style?: CSSProperties
    greyBadges?: boolean
}

const PropertyFiltersDisplay: React.FunctionComponent<Props> = ({ filters, style, greyBadges }: Props) => {
    return (
        <div className="property-filters mb" style={style}>
            {filters &&
                filters.map((item) => {
                    return <PropertyFilterButton key={item.key} item={item} greyBadges={greyBadges} />
                })}
        </div>
    )
}

export default PropertyFiltersDisplay
