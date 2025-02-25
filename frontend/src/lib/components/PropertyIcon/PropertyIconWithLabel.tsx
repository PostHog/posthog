import clsx from 'clsx'
import { forwardRef, Ref } from 'react'

import { PropertyIconStandalone } from './PropertyIconStandalone'
import { PropertyIconProps } from './types'

export const PropertyIconWithLabel = forwardRef(function PropertyIconWithLabel(
    { property, value, className }: PropertyIconProps,
    ref: Ref<HTMLDivElement>
): JSX.Element {
    return (
        <div className={clsx('inline-flex items-center gap-2', className)}>
            <PropertyIconStandalone property={property} value={value} ref={ref} />
            <span>{value}</span>
        </div>
    )
})
