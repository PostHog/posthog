import React, { CSSProperties } from 'react'
import { AnyPropertyFilter } from '~/types'
import { PropertyFilterButton } from './PropertyFilterButton'

type Props = {
    filters: AnyPropertyFilter[]
    style?: CSSProperties
}

const PropertyFiltersDisplay: React.FunctionComponent<Props> = ({ filters, style }: Props) => {
    return (
        <div className="PropertyFilters mb-4" style={style}>
            {filters &&
                filters.map((item, idx) => {
                    return (
                        <>
                            {' '}
                            <PropertyFilterButton style={{ margin: '0.1rem' }} key={item.key} item={item} />{' '}
                            {idx !== filters.length - 1 ? ',' : ''}
                        </>
                    )
                })}
        </div>
    )
}

export default PropertyFiltersDisplay
