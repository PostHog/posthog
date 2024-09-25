import { Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PropertyIcon } from 'lib/components/PropertyIcon'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { getCoreFilterDefinition } from 'lib/taxonomy'
import { countryCodeToName } from 'scenes/insights/views/WorldMap'

import { SessionRecordingType } from '~/types'

import { playerMetaLogic } from '../playerMetaLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'



function OverviewCard({ item }: { item: OverviewItem }): JSX.Element {
    return (
        <Tooltip title={item.tooltipTitle}>
            <div className="flex-1 p-2 text-center">
                <div className="text-sm">{item.label}</div>
                <div className="text-lg font-semibold">
                    {item.type === 'icon' ? <PropertyIcon property={item.property} value={item.value} /> : item.value}
                </div>
            </div>
        </Tooltip>
    )
}

export function OverviewCardRow({ items }: { items: OverviewItem[] }): JSX.Element {
    return (
        <div className="grid grid-cols-3 place-items-center rounded border bg-bg-light m-2">
            {items.map((item) => (
                <OverviewCard key={item.label} item={item} />
            ))}
        </div>
    )
}

export function PlayerSidebarOverviewTab(): JSX.Element {
    const { logicProps } = useValues(sessionRecordingPlayerLogic)
    const { sessionPlayerMetaData } = useValues(playerMetaLogic(logicProps))

    const items = sessionPlayerMetaDataToOverviewItems(sessionPlayerMetaData)

    return (
        <div className="flex flex-col overflow-auto bg-bg-3000 h-full">
            <OverviewCardRow items={items} />
        </div>
    )
}
