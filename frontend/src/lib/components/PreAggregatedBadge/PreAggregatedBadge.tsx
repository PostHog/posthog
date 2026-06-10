import clsx from 'clsx'

import { IconBolt, IconDatabaseBolt } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

export type PreAggregatedBadgeVariant = 'preagg' | 'precomputed'
export type PreAggregatedBadgePosition = 'top-right' | 'bottom-right'

interface PreAggregatedBadgeProps {
    variant?: PreAggregatedBadgeVariant
    position?: PreAggregatedBadgePosition
}

const POSITION_CLASS: Record<PreAggregatedBadgePosition, string> = {
    'top-right': 'top-2 right-2',
    'bottom-right': 'bottom-2 right-2',
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

export function PreAggregatedBadge({
    variant = 'preagg',
    position = 'top-right',
}: PreAggregatedBadgeProps = {}): JSX.Element {
    const { tooltip, iconClassName, Icon } = VARIANT_CONFIG[variant]
    return (
        <Tooltip title={tooltip}>
            <div className={clsx('absolute z-10', POSITION_CLASS[position])}>
                <Icon className={iconClassName} />
            </div>
        </Tooltip>
    )
}
