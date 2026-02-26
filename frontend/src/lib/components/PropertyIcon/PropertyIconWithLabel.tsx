import { PropertyIconStandalone } from './PropertyIconStandalone'
import { PropertyIconProps } from './types'

export function PropertyIconWithLabel({ ref, property, value, className }: PropertyIconProps): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <PropertyIconStandalone property={property} value={value} ref={ref} className={className} />
            <span>{value}</span>
        </div>
    )
}
