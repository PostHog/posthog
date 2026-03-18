import { IconBolt } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

export function PreAggregatedBadge(): JSX.Element {
    return (
        <Tooltip title="Optimized with new query engine">
            <div className="absolute top-2 right-2 z-10">
                <IconBolt className="text-warning w-4 h-4" />
            </div>
        </Tooltip>
    )
}
