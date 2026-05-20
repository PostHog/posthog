import { IconBolt } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

export type PreAggregatedBadgeVariant = 'preagg' | 'lazy'

interface PreAggregatedBadgeProps {
    variant?: PreAggregatedBadgeVariant
}

const VARIANT_CONFIG: Record<PreAggregatedBadgeVariant, { tooltip: string; iconClassName: string }> = {
    preagg: {
        tooltip: 'Optimized with new query engine',
        iconClassName: 'text-warning w-4 h-4',
    },
    lazy: {
        tooltip: 'Served from lazy precompute',
        iconClassName: 'text-success w-4 h-4',
    },
}

export function PreAggregatedBadge({ variant = 'preagg' }: PreAggregatedBadgeProps = {}): JSX.Element {
    const { tooltip, iconClassName } = VARIANT_CONFIG[variant]
    return (
        <Tooltip title={tooltip}>
            <div className="absolute top-2 right-2 z-10">
                <IconBolt className={iconClassName} />
            </div>
        </Tooltip>
    )
}
