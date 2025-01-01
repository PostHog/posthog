import { useValues } from 'kea'
import { PropertyIcon } from 'lib/components/PropertyIcon'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { OverviewGrid, OverviewGridItem } from '../../components/OverviewGrid'
import { playerMetaLogic } from '../playerMetaLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

export function PlayerSidebarOverviewGrid(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { overviewItems, loading } = useValues(playerMetaLogic(logicProps))

    return (
        <div className="rounded border bg-bg-light m-2">
            {loading ? (
                <div className="flex flex-col space-y-1 px-1 py-0.5">
                    <LemonSkeleton.Row repeat={6} className="h-5" />
                </div>
            ) : (
                <OverviewGrid>
                    {overviewItems.map((item) => {
                        return (
                            <OverviewGridItem
                                key={item.label}
                                description={item.tooltipTitle}
                                label={item.label}
                                icon={item.icon}
                            >
                                <div className="flex flex-row items-center space-x-2">
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
