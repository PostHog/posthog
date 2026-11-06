import { useValues } from 'kea'

import { Skeleton, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { cn } from 'lib/utils/css-classes'
import { OVERVIEW_STAT_LABELS } from 'scenes/session-recordings/player/player-meta/overviewTabs'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'

import { OverviewItem } from '../../components/OverviewGrid'
import { QuillOverviewRows } from './QuillOverviewRows'

export function QuillOverviewSessionCard(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { overviewItemsByTab, loading } = useValues(playerMetaLogic(logicProps))

    const isStat = (item: OverviewItem): boolean => item.type === 'text' && OVERVIEW_STAT_LABELS.includes(item.label)
    const statItems = overviewItemsByTab.session.filter(isStat)
    const rowItems = overviewItemsByTab.session.filter((item) => !isStat(item))

    return (
        <>
            {statItems.length > 0 && (
                <div className="rounded border border-border bg-card flex items-center justify-between gap-2 px-2 py-1.5">
                    {statItems.map((item) =>
                        loading ? (
                            <Skeleton key={item.label} className="h-8 flex-1" />
                        ) : (
                            <Tooltip key={item.label}>
                                <TooltipTrigger render={<span className="flex flex-col items-center min-w-0 flex-1" />}>
                                    <span
                                        className={cn(
                                            'font-semibold tabular-nums truncate max-w-full',
                                            item.label === 'Errors' && Number(item.value) > 0 && 'text-destructive'
                                        )}
                                    >
                                        {item.value}
                                    </span>
                                    <span className="text-xs text-muted-foreground truncate max-w-full">
                                        {item.label}
                                    </span>
                                </TooltipTrigger>
                                {item.keyTooltip && <TooltipContent>{item.keyTooltip}</TooltipContent>}
                            </Tooltip>
                        )
                    )}
                </div>
            )}
            <QuillOverviewRows items={rowItems} pickerGroupType={TaxonomicFilterGroupType.SessionProperties} />
        </>
    )
}
