import './PropertyIcons.scss'

import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { countryTitleFrom } from 'scenes/session-recordings/player/player-meta/countryTitleFrom'

import { SessionRecordingType } from '~/types'

interface GatheredProperty {
    property: string
    value: string | undefined
    label: string | undefined
}

const browserIconPropertyKeys = ['$geoip_country_code', '$browser', '$device_type', '$os']
const mobileIconPropertyKeys = ['$geoip_country_code', '$device_type', '$os_name']

export function gatherIconProperties(
    recordingProperties: Record<string, any> | undefined,
    recording?: SessionRecordingType
): GatheredProperty[] {
    const iconProperties =
        recordingProperties && Object.keys(recordingProperties).length > 0
            ? recordingProperties
            : recording?.person?.properties || {}

    const deviceType = iconProperties['$device_type'] || iconProperties['$initial_device_type']
    const iconPropertyKeys = deviceType === 'Mobile' ? mobileIconPropertyKeys : browserIconPropertyKeys

    return iconPropertyKeys
        .flatMap((property) => {
            const value = property === '$device_type' ? deviceType : iconProperties[property]
            const label = property === '$geoip_country_code' ? countryTitleFrom(iconProperties) : value

            return { property, value, label }
        })
        .filter((property) => !!property.value)
}

export interface PropertyIconsProps {
    recordingProperties: GatheredProperty[]
    loading?: boolean
    iconClassNames?: string
    showTooltip?: boolean
    showLabel?: (key: string) => boolean
}

export function PropertyIcons({ recordingProperties, loading, iconClassNames }: PropertyIconsProps): JSX.Element {
    return (
        <div className="flex gap-x-1 ph-no-capture">
            {loading ? (
                <LemonSkeleton className="w-16 h-3" />
            ) : (
                recordingProperties.map(({ property, value, label }) => (
                    <Tooltip key={property} title={label}>
                        <span className="flex items-center gap-x-0.5">
                            <PropertyIcon className={iconClassNames} property={property} value={value} />
                            <span className="SessionRecordingPreview__property-label text-secondary truncate">
                                {label}
                            </span>
                        </span>
                    </Tooltip>
                ))
            )}
        </div>
    )
}
