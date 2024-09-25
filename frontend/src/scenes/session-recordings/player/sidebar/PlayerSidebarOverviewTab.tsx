import { useValues } from 'kea'
import { PropertyIcon } from 'lib/components/PropertyIcon'

import { OverviewGrid, OverviewGridItem } from '../../components/OverviewGrid'
import { playerMetaLogic } from '../playerMetaLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

export function PlayerSidebarOverviewTab(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { overviewItems } = useValues(playerMetaLogic(logicProps))

    return (
        <div className="flex flex-col overflow-auto bg-bg-3000 h-full">
            <div className="rounded border bg-bg-light m-2">
                <OverviewGrid>
                    {overviewItems.map((item) => (
                        <OverviewGridItem key={item.label} description={item.tooltipTitle} label={item.label}>
                            {item.type === 'icon' ? (
                                <PropertyIcon property={item.property} value={item.value} />
                            ) : (
                                item.value
                            )}
                        </OverviewGridItem>
                    ))}
                </OverviewGrid>
            </div>
        </div>
    )
}
