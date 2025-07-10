import { Ref, forwardRef } from 'react'

import { PropertyIconStandalone } from './PropertyIconStandalone'
import { PropertyIconProps } from './types'

export const PropertyIconWithLabel = forwardRef(function PropertyIconWithLabel(
    { property, value, className }: PropertyIconProps,
    ref: Ref<HTMLDivElement>
): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <PropertyIconStandalone property={property} value={value} ref={ref} className={className} />
            <span>{value}</span>
        </div>
    )
})
