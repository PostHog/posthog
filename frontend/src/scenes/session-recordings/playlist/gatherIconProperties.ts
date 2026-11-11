import { countryTitleFrom } from 'scenes/session-recordings/player/player-meta/countryTitleFrom'

import { SessionRecordingType } from '~/types'

export interface GatheredProperty {
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
