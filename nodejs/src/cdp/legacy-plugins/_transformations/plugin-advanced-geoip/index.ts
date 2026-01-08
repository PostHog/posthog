import { PluginEvent } from '@posthog/plugin-scaffold'

import { LegacyTransformationPluginMeta } from '../../types'

const geoIpProps = [
    '$geoip_city_name',
    '$geoip_country_name',
    '$geoip_country_code',
    '$geoip_continent_name',
    '$geoip_continent_code',
    '$geoip_postal_code',
    '$geoip_latitude',
    '$geoip_longitude',
    '$geoip_time_zone',
    '$geoip_subdivision_1_code',
    '$geoip_subdivision_1_name',
    '$geoip_subdivision_2_code',
    '$geoip_subdivision_2_name',
    '$geoip_subdivision_3_code',
    '$geoip_subdivision_3_name',
]

const geoIpInitialProps = [
    '$initial_geoip_city_name',
    '$initial_geoip_country_name',
    '$initial_geoip_country_code',
    '$initial_geoip_continent_name',
    '$initial_geoip_continent_code',
    '$initial_geoip_postal_code',
    '$initial_geoip_latitude',
    '$initial_geoip_longitude',
    '$initial_geoip_time_zone',
    '$initial_geoip_subdivision_1_code',
    '$initial_geoip_subdivision_1_name',
    '$initial_geoip_subdivision_2_code',
    '$initial_geoip_subdivision_2_name',
    '$initial_geoip_subdivision_3_code',
    '$initial_geoip_subdivision_3_name',
]

// interface AppInterface {
//     config: {
//         discardIp: 'true' | 'false'
//         discardLibs: string
//     }
// }

const GEO_IP_PLUGIN = /^GeoIP \(\d+\)$/

export const processEvent = (event: PluginEvent, { config, logger }: LegacyTransformationPluginMeta) => {
    const parsedLibs = config.discardLibs?.split(',').map((val: string) => val.toLowerCase().trim())

    if (parsedLibs && event.properties?.$lib && parsedLibs.includes(event.properties?.$lib)) {
        // Event comes from a `$lib` that should be ignored
        logger.log(
            `Discarding GeoIP properties from ${event.uuid || event.event} as event comes from ignored $lib: ${
                event.properties?.$lib
            }.`
        )
        for (const prop of geoIpProps) {
            // We need to handle both `$set` and `properties.$set` as they are both used in different contexts
            if (event.$set) {
                delete event.$set[prop]
            }

            if (event.properties.$set) {
                delete event.properties.$set[prop]
            }
            delete event.properties[prop]
        }

        for (const prop of geoIpInitialProps) {
            if (event.$set_once) {
                delete event.$set_once[prop]
            }

            if (event.properties.$set_once) {
                delete event.properties.$set_once[prop]
            }
        }
    }

    if (config.discardIp === 'true') {
        if (
            Array.isArray(event.properties?.$plugins_succeeded) &&
            event.properties?.$plugins_succeeded.find((val: string) => val.toString().match(GEO_IP_PLUGIN))
        ) {
            event.properties.$ip = undefined
            event.ip = null
            logger.log(`IP discarded for event ${event.uuid || event.event}.`)
        } else {
            logger.warn(`Could not discard IP for event ${event.uuid || event.event} as GeoIP has not been processed.`)
        }
    }

    logger.log(`Finished processing ${event.uuid || event.event}.`)

    return event
}
