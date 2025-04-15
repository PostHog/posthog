import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'
import { countryTitleFrom } from 'scenes/session-recordings/player/player-meta/playerMetaLogic'

import { PropertyIcon } from '../PropertyIcon/PropertyIcon'

interface GatheredProperty {
    property: string
    value: string | undefined
    label: string | undefined
}

export interface PropertyIconsProps {
    properties: Record<string, any>
    loading?: boolean
    iconClassNames?: string
    showTooltip?: boolean
    showLabel?: (key: string) => boolean
}

export const PropertyIcons = ({ properties, loading, iconClassNames }: PropertyIconsProps): JSX.Element | null => {
    const iconProperties = gatherIconProperties(properties)

    return (
        <div className="flex deprecated-space-x-1 ph-no-capture">
            {loading ? (
                <LemonSkeleton className="w-16 h-3" />
            ) : (
                iconProperties.map(({ property, value, label }) => (
                    <Tooltip key={property} title={label}>
                        <PropertyIcon className={iconClassNames} property={property} value={value} />
                    </Tooltip>
                ))
            )}
        </div>
    )
}

const browserIconPropertyKeys = ['$geoip_country_code', '$browser', '$device_type', '$os']
const mobileIconPropertyKeys = ['$geoip_country_code', '$device_type', '$os_name']

function gatherIconProperties(properties: Record<string, any>): GatheredProperty[] {
    const iconProperties = properties

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
