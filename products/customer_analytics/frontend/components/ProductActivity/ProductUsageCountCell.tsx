import { CountCell } from 'lib/components/DotMatrix/CountCell'
import { IconRobot } from 'lib/lemon-ui/icons'

import { ProductUsageFirstUseStar } from './ProductUsageFirstUseStar'
import { getProductUsageCountScale } from './productUsagePresentation'

export function ProductUsageCountCell({
    value,
    users = true,
    firstUse = false,
    agent = false,
    label,
}: {
    value: number
    users?: boolean
    firstUse?: boolean
    /** Some of these people used the product through an AI agent. */
    agent?: boolean
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
            {agent && value > 0 && (
                <span
                    className="absolute -bottom-1 -right-1 flex text-[10px] text-purple-500 bg-surface-primary rounded-full"
                    role="img"
                    aria-label="Includes AI agent activity"
                    data-attr="product-usage-agent-marker"
                >
                    <IconRobot />
                </span>
            )}
        </div>
    )
}
