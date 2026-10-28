import { useValues } from 'kea'

import { Skeleton, Text, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { modelsOverviewLogic } from './modelsOverviewLogic'
import { OverviewStatItem } from './overviewStatItems'

const TONE_CLASS: Record<'danger' | 'warning', string> = {
    danger: 'text-destructive-foreground',
    warning: 'text-warning-foreground',
}

function Stat({ item }: { item: OverviewStatItem }): JSX.Element {
    const number = (
        <span translate="no" className={cn('text-xl font-semibold tabular-nums', item.tone && TONE_CLASS[item.tone])}>
            {item.value}
        </span>
    )
    return (
        <div className="flex flex-col" data-attr={item.dataAttr}>
            {item.loading ? (
                <Skeleton className="h-7 w-10" />
            ) : item.tooltip ? (
                <Tooltip>
                    <TooltipTrigger delay={0} render={<span className="inline-flex" />}>
                        {number}
                    </TooltipTrigger>
                    <TooltipContent>{item.tooltip}</TooltipContent>
                </Tooltip>
            ) : (
                number
            )}
            <Text size="xs" variant="muted">
                {item.label}
            </Text>
        </div>
    )
}

export function ModelsOverviewStats(): JSX.Element {
    const { statItems } = useValues(modelsOverviewLogic)

    return (
        <div className="flex flex-wrap gap-x-8 gap-y-3" data-attr="models-overview-stats">
            {statItems.map((item) => (
                <Stat key={item.dataAttr} item={item} />
            ))}
        </div>
    )
}
