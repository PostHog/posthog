import { IconBolt, IconDatabaseBolt } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

export type PreAggregatedBadgeVariant = 'preagg' | 'precomputed'

interface PreAggregatedBadgeProps {
    variant?: PreAggregatedBadgeVariant
}

const VARIANT_CONFIG: Record<
    PreAggregatedBadgeVariant,
    { tooltip: string; iconClassName: string; Icon: typeof IconBolt }
> = {
    preagg: {
        tooltip: 'Optimized with new query engine',
        iconClassName: 'text-warning w-4 h-4',
        Icon: IconBolt,
    },
    precomputed: {
        tooltip: 'Loaded from a pre-computed dataset',
        iconClassName: 'text-muted w-4 h-4',
        Icon: IconDatabaseBolt,
    },
}

export function PreAggregatedBadge({ variant = 'preagg' }: PreAggregatedBadgeProps = {}): JSX.Element {
    const { tooltip, iconClassName, Icon } = VARIANT_CONFIG[variant]
    return (
        <Tooltip title={tooltip}>
            <div className="absolute top-2 right-2 z-10">
                <Icon className={iconClassName} />
            </div>
        </Tooltip>
    )
}
