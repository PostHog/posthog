import { CountCell } from 'lib/components/DotMatrix/CountCell'

import { ProductUsageFirstUseStar } from './ProductUsageFirstUseStar'
import { getProductUsageCountScale } from './productUsagePresentation'

export function ProductUsageCountCell({
    value,
    users = true,
    firstUse = false,
    label,
}: {
    value: number
    users?: boolean
    firstUse?: boolean
    label?: string
}): JSX.Element {
    return (
        <div className="relative inline-flex items-center">
            <CountCell value={value} size="small" scale={getProductUsageCountScale(users)} label={label} />
            {firstUse && value > 0 && (
                <ProductUsageFirstUseStar
                    className="absolute -top-1 -right-1"
                    color="var(--color-orange-500)"
                    label="First use ever"
                />
            )}
        </div>
    )
}
