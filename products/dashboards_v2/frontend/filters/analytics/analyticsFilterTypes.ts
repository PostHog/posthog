import { createPropertyFilter } from '../property/createPropertyFilter'
import { eventPropertyValues } from './eventPropertyValues'
import { searchProjectProperties } from './searchProjectProperties'

export const ANALYTICS_FILTER_TYPES = [
    createPropertyFilter({
        featured: [
            { key: '$browser', label: 'Browser' },
            { key: '$os', label: 'OS' },
            { key: '$device_type', label: 'Device type' },
            { key: '$geoip_country_name', label: 'Country' },
        ],
        search: { label: 'More properties', load: searchProjectProperties },
        values: eventPropertyValues,
    }),
]
