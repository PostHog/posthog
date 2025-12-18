import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

export const WEB_ANALYTICS_PRE_AGGREGATED_ALLOWED_EVENT_PROPERTIES = [
    '$host',
    '$device_type',
    '$browser',
    '$os',
    '$referring_domain',
    '$geoip_country_code',
    '$geoip_city_name',
    '$geoip_subdivision_1_code',
    '$geoip_subdivision_1_name',
    '$geoip_time_zone',
    '$pathname',
    'metadata.loggedIn',
    'metadata.backend',
]

export const WEB_ANALYTICS_PRE_AGGREGATED_ALLOWED_SESSION_PROPERTIES = [
    '$entry_pathname',
    '$end_pathname',
    '$entry_utm_source',
    '$entry_utm_medium',
    '$entry_utm_campaign',
    '$entry_utm_term',
    '$entry_utm_content',
    '$channel_type',
]

export const WEB_ANALYTICS_PRE_AGGREGATED_PROPERTY_ALLOW_LIST = {
    [TaxonomicFilterGroupType.EventProperties]: WEB_ANALYTICS_PRE_AGGREGATED_ALLOWED_EVENT_PROPERTIES,
    [TaxonomicFilterGroupType.SessionProperties]: WEB_ANALYTICS_PRE_AGGREGATED_ALLOWED_SESSION_PROPERTIES,
}

export const PROPERTY_CURRENT_URL = '$current_url' as const
export const PROPERTY_HOST = '$host' as const
export const PROPERTY_PATHNAME = '$pathname' as const

export const hasURLSearchParams = (filter: AnyPropertyFilter): boolean => {
    if (filter.key !== PROPERTY_CURRENT_URL || filter.type !== PropertyFilterType.Event) {
        return false
    }

    try {
        const urlValue = Array.isArray(filter.value) ? filter.value[0] : filter.value
        if (typeof urlValue === 'string') {
            const url = new URL(urlValue)
            return !!(url.search && url.search !== '?')
        }
    } catch {
        return true
    }

    return false
}

export const convertCurrentURLFilter = (
    filter: AnyPropertyFilter
): { key: string; value: string; operator: PropertyOperator; type: PropertyFilterType.Event }[] | null => {
    if (filter.key !== PROPERTY_CURRENT_URL || filter.type !== PropertyFilterType.Event) {
        return null
    }

    try {
        const urlValue = Array.isArray(filter.value) ? filter.value[0] : filter.value
        if (typeof urlValue === 'string') {
            const url = new URL(urlValue)
            if (!url.search || url.search === '?') {
                return [
                    {
                        key: PROPERTY_HOST,
                        value: url.host,
                        operator: filter.operator,
                        type: PropertyFilterType.Event,
                    },
                    {
                        key: PROPERTY_PATHNAME,
                        value: url.pathname,
                        operator: filter.operator,
                        type: PropertyFilterType.Event,
                    },
                ]
            }
        }
    } catch {
        // URL parsing failed
    }

    return null
}
