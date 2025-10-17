import { useValues } from 'kea'

import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { playerMetaLogic } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'

import { OverviewGrid, OverviewGridItem } from '../../components/OverviewGrid'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

export function PlayerSidebarOverviewGrid(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { overviewItems, loading } = useValues(playerMetaLogic(logicProps))
    return (
        <div className="rounded border bg-surface-primary">
            {loading ? (
                <div className="flex flex-col deprecated-space-y-1">
                    <LemonSkeleton.Row repeat={6} className="h-5" />
                </div>
            ) : (
                <OverviewGrid>
                    {overviewItems.map((item) => {
                        return (
                            <OverviewGridItem
                                key={item.label}
                                description={item.valueTooltip}
                                label={item.label}
                                icon={item.icon}
                                itemKeyTooltip={item.keyTooltip}
                                fadeLabel
                            >
                                <div className="flex flex-row items-center deprecated-space-x-2 justify-start font-medium">
                                    {item.type === 'property' && (
                                        <PropertyIcon property={item.property} value={item.value} />
                                    )}
                                    <span>{item.value}</span>
                                </div>
                            </OverviewGridItem>
                        )
                    })}
                </OverviewGrid>
            )}
        </div>
    )
}
