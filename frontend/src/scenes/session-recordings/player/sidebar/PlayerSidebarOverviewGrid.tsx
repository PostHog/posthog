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
        <div className="bg-surface-primary rounded border">
            {loading ? (
                <div className="deprecated-space-y-1 flex flex-col">
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
                                <div className="deprecated-space-x-2 flex flex-row items-center justify-start font-medium">
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
