import { Tooltip } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { PropertyIcon } from 'lib/components/PropertyIcon'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { getCoreFilterDefinition } from 'lib/taxonomy'
import { countryCodeToName } from 'scenes/insights/views/WorldMap'

import { SessionRecordingType } from '~/types'

import { playerMetaLogic } from '../playerMetaLogic'
import { sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'

interface OverviewItem {
    property: string
    label: string
    value: string
    type: 'text' | 'icon'
    tooltipTitle?: string
}

const browserPropertyKeys = ['$geoip_country_code', '$browser', '$device_type', '$os']
const mobilePropertyKeys = ['$geoip_country_code', '$device_type', '$os_name']
const recordingPropertyKeys = ['click_count', 'keypress_count', 'console_error_count'] as const

function sessionPlayerMetaDataToOverviewItems(sessionPlayerMetaData: SessionRecordingType | null): OverviewItem[] {
    const items: OverviewItem[] = []

    recordingPropertyKeys.forEach((property) => {
        if (sessionPlayerMetaData?.[property]) {
            items.push({
                label: getCoreFilterDefinition(property, TaxonomicFilterGroupType.Replay)?.label ?? property,
                value: `${sessionPlayerMetaData[property]}`,
                type: 'text',
                property,
            })
        }
    })

    const personProperties = sessionPlayerMetaData?.person?.properties ?? {}

    const deviceType = personProperties['$device_type'] || personProperties['$initial_device_type']
    const deviceTypePropertyKeys = deviceType === 'Mobile' ? mobilePropertyKeys : browserPropertyKeys

    deviceTypePropertyKeys.forEach((property) => {
        if (personProperties[property]) {
            const value = personProperties[property]

            const tooltipTitle =
                property === '$geoip_country_code' && value in countryCodeToName
                    ? countryCodeToName[value as keyof typeof countryCodeToName]
                    : value

            items.push({
                label: getCoreFilterDefinition(property, TaxonomicFilterGroupType.PersonProperties)?.label ?? property,
                value,
                tooltipTitle,
                type: 'icon',
                property,
            })
        }
    })

    return items
}

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
