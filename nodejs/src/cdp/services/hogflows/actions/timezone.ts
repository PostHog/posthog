import { DateTime } from 'luxon'

import { CyclotronPerson } from '~/cdp/types'

const GEOIP_TIMEZONE_PROPERTY = '$geoip_time_zone'

/** The timezone fields carried by every step that reasons about local time. */
export interface TimezoneConfig {
    timezone?: string | null
    use_person_timezone?: boolean
    fallback_timezone?: string | null
}

function isValidTimezone(timezone: string): boolean {
    // Luxon returns an invalid DateTime if the timezone is not recognized
    return DateTime.utc().setZone(timezone).isValid
}

/** The zone a step reads local time in: the person's own when asked for and usable, else the configured one. */
export function resolveTimezone(config: TimezoneConfig, person?: CyclotronPerson): string {
    const fallback = config.fallback_timezone || config.timezone || 'UTC'

    if (config.use_person_timezone) {
        if (person?.properties) {
            const personTimezone = person.properties[GEOIP_TIMEZONE_PROPERTY]
            if (personTimezone && typeof personTimezone === 'string' && isValidTimezone(personTimezone)) {
                return personTimezone
            }
        }
        // Fall back if person doesn't exist, doesn't have a timezone, or timezone is invalid
        return fallback
    }
    // Use the configured timezone or default to UTC
    return config.timezone || 'UTC'
}
