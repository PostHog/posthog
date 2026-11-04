import { CountCell } from 'lib/components/DotMatrix/CountCell'
import { DotMatrixSymbol } from 'lib/components/DotMatrix/DotMatrixSymbol'

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
                <svg
                    className="absolute -top-1 -right-1"
                    width="17"
                    height="17"
                    viewBox="0 0 17 17"
                    role="img"
                    aria-label="First use ever"
                >
                    <DotMatrixSymbol value={1} thresholds={[1]} firstUse color="var(--color-text-warning)" />
                </svg>
            )}
        </div>
    )
}
